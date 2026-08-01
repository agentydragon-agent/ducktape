"""Integration tests: validate real cluster/k8s/ config via pure analysis.

Tests that parse the cluster kustomization tree and check structural invariants
(no orphaned files, valid dependencies, health checks on controller resources,
blueprint completeness). All kustomizations are built with kustomize to validate
they render correctly and to provide build results for resource-level checks.

These Bazel tests are the single source of truth for cluster validation; the
former `cluster-validate` pre-commit hook was removed in favor of running them
(and the sibling `test_*.py` targets) in CI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_bazel
import yaml

from cluster.validation.authentik_blueprints import (
    check_blueprint_completeness,
    check_proxy_provider_outpost_assignment,
)
from cluster.validation.checks import (
    check_duplicate_external_secrets,
    check_goldilocks_explicit_decision,
    check_goldilocks_namespace_labels,
    check_sops_decryption_blocks,
    find_orphaned_files,
)
from cluster.validation.cluster import ParsedCluster, parse_cluster
from cluster.validation.crd_layering import CrdLayeringViolationError, check_crd_layering
from cluster.validation.dependencies import validate_dependencies
from cluster.validation.flux_bootstrap_auth import check_flux_bootstrap_auth
from cluster.validation.health_checks import check_controller_health_checks, check_retry_policy
from cluster.validation.image_automation import check_image_automation_webhook
from cluster.validation.kustomize import KustomizeBuildResult, run_kustomize_build
from cluster.validation.terraform_backends import check_terraform_backends
from util.bazel.runfiles import get_required_path

_K8S_ROOT_KUSTOMIZATION = "_main/cluster/k8s/kustomization.yaml"


@pytest.fixture(scope="session")
def k8s_dir() -> Path:
    return get_required_path(_K8S_ROOT_KUSTOMIZATION).parent


def _local_flux_kust_names(parsed: ParsedCluster, k8s_dir: Path) -> set[str]:
    """Active flux kustomization names whose spec.path points into the local cluster/k8s tree."""
    return {name for name, spec in parsed.active_flux_kustomizations.items() if spec.local_dir(k8s_dir)}


@pytest.fixture(scope="session")
def cluster(k8s_dir: Path) -> ParsedCluster:
    """Parse cluster and build flux-referenced kustomizations (hard failure on any build error)."""
    parsed = parse_cluster(k8s_dir)

    # Build all local flux-referenced kustomizations (including suspended — kustomize
    # build should still succeed). Only validation checks filter suspended.
    local_dirs = {d for spec in parsed.flux_kustomizations.values() if (d := spec.local_dir(k8s_dir))}
    kust_files = [k for k in parsed.kustomize_files if k.parent.resolve() in local_dirs]

    async def _build_all() -> list[KustomizeBuildResult]:
        return list(await asyncio.gather(*[run_kustomize_build(k) for k in kust_files]))

    parsed.build_results = asyncio.run(_build_all())
    return parsed


def test_all_local_flux_kustomizations_have_build_results(cluster: ParsedCluster, k8s_dir: Path) -> None:
    """Every flux kustomization pointing to a local path must have a build result."""
    covered = set(cluster.flux_kust_resources(k8s_dir))
    expected = _local_flux_kust_names(cluster, k8s_dir)
    missing = sorted(expected - covered)
    assert not missing, "Flux kustomizations with no build result:\n" + "\n".join(f"  {m}" for m in missing)


def test_no_dependency_errors(cluster: ParsedCluster, k8s_dir: Path) -> None:
    """No cycles, required dependencies present, operator dependencies satisfied."""
    errors = validate_dependencies(cluster, k8s_dir)
    assert not errors, "\n".join(errors)


def test_controller_resources_have_health_checks(cluster: ParsedCluster, k8s_dir: Path) -> None:
    errors = check_controller_health_checks(cluster, k8s_dir)
    assert not errors, "\n".join(errors)


def test_no_crd_layering_violations(cluster: ParsedCluster, k8s_dir: Path) -> None:
    """Active kustomizations must not mix HelmReleases with external-operator CRD instances."""
    active_dirs = {spec.local_dir(k8s_dir) for spec in cluster.active_flux_kustomizations.values()}
    errors: list[str] = []
    for result in cluster.build_results:
        if result.kustomization_path.parent.resolve() not in active_dirs:
            continue
        try:
            check_crd_layering(result)
        except CrdLayeringViolationError as e:
            errors.append(str(e))
    assert not errors, "\n".join(errors)


def test_single_external_secrets_installation(cluster: ParsedCluster) -> None:
    """Exactly one external-secrets HelmRelease across the cluster."""
    errors = check_duplicate_external_secrets(cluster.build_results)
    assert not errors, "\n".join(errors)


def test_haku_claude_oauth_proxy_isolated_from_general_sandbox(k8s_dir: Path) -> None:
    """Only the dedicated Console runner namespace receives Claude OAuth proxy authority."""
    template = yaml.safe_load((k8s_dir / "haku/workspaces/app/sandboxtemplate-haku-claude.yaml").read_text())
    assert template["metadata"]["namespace"] == "haku-claude-sandbox"

    mounts = template["spec"]["podTemplate"]["spec"]["containers"][0]["volumeMounts"]
    assert sum(mount["mountPath"] == "/egress-proxy-ca" for mount in mounts) == 1

    oauth_ingress = yaml.safe_load((k8s_dir / "agents/haku-egress-proxy/claude-networkpolicy.yaml").read_text())
    peers = oauth_ingress["spec"]["ingress"][0]["from"]
    allowed_namespaces = {peer["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] for peer in peers}
    assert allowed_namespaces == {"haku-claude-sandbox"}

    general_egress = (k8s_dir / "agents/haku-egress-proxy/ccnp-haku-proxy-egress.yaml").read_text()
    assert "haku-claude-oauth-proxy" not in general_egress

    claude_egress = (k8s_dir / "agents/haku-egress-proxy/ccnp-haku-claude-sandbox-egress.yaml").read_text()
    assert "haku-claude-sandbox" in claude_egress
    assert "haku-claude-oauth-proxy" in claude_egress

    general_injection = (k8s_dir / "kyverno/policies/inject-haku-egress-proxy.yaml").read_text()
    assert "haku-claude-sandbox" not in general_injection

    console_config = yaml.safe_load((k8s_dir / "haku/console/config.yaml").read_text())
    assert console_config["claude_runtime"] == {
        "namespace": "haku-claude-sandbox",
        "warm_pool": "haku-claude",
        "cwd": "/workspace",
        "session_ttl_seconds": 7200,
        "prompt_poll_seconds": 0.25,
        "oauth_placeholder": "sk-ant-oat01-proxy-haku-claude-placeholder",
        "https_proxy": "http://haku-claude-oauth-proxy.haku-egress-proxy.svc.cluster.local:8180",
        "ca_bundle": "/egress-proxy-ca/ca-certificates.crt",
        "no_proxy": "127.0.0.1,localhost,.svc,.svc.cluster.local,kubernetes.default.svc,10.0.0.0/8",
    }
    deployment = yaml.safe_load((k8s_dir / "haku/console/deployment.yaml").read_text())
    env_names = {entry["name"] for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert not any(name.startswith("HAKU_CONSOLE_CLAUDE_RUNTIME__") for name in env_names)


def test_terraform_backends_not_kubernetes(cluster: ParsedCluster) -> None:
    """tofu-controller Terraform CRs must use the pg backend, not kubernetes Secrets."""
    errors = check_terraform_backends(cluster)
    assert not errors, "\n".join(errors)


def test_image_automation_webhook_consistency(cluster: ParsedCluster) -> None:
    """Every rendered ImageRepository is in the webhook Receiver; every ImagePolicy ref resolves.

    Runs against the real built cluster (not synthetic fixtures), so it also guards the
    check against crashing on the actual manifest set — the gap that hid the earlier
    raw-YAML-walking bug.
    """
    errors = check_image_automation_webhook(cluster)
    assert not errors, "\n".join(errors)


def test_flux_bootstrap_auth_split(cluster: ParsedCluster, k8s_dir: Path) -> None:
    """Cold bootstrap sources must not depend on Flux-decrypted auth; write sources must."""
    errors = check_flux_bootstrap_auth(cluster, k8s_dir)
    assert not errors, "\n".join(errors)


def test_sops_secrets_have_decryption_block(cluster: ParsedCluster, k8s_dir: Path) -> None:
    """Active flux kustomizations rendering a SOPS Secret must declare decryption.provider: sops."""
    errors = check_sops_decryption_blocks(cluster, k8s_dir)
    assert not errors, "\n".join(errors)


def test_ntfy_provider_headers_parse_as_yaml_map(k8s_dir: Path) -> None:
    """notification-controller parses Provider secret `headers` as a YAML string map."""
    secret_path = k8s_dir / "flux-webhook" / "ntfy-webhook.sops.yaml"
    secret = yaml.safe_load(secret_path.read_text())
    headers = yaml.safe_load(secret["stringData"]["headers"])

    assert isinstance(headers, dict)
    assert headers
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in headers.items())


def test_haku_console_deployment_version_contract(k8s_dir: Path) -> None:
    """The runtime commit stamp and cache-safe rollout strategy must track the actual images."""
    deployment_path = k8s_dir / "haku" / "console" / "deployment.yaml"
    raw = deployment_path.read_text(encoding="utf-8")
    deployment = yaml.safe_load(raw)

    assert deployment["spec"]["strategy"] == {"type": "Recreate"}
    containers = {container["name"]: container for container in deployment["spec"]["template"]["spec"]["containers"]}
    runtime_tags = {entry["name"]: entry["value"] for entry in containers["server"]["env"] if "value" in entry}
    assert containers["server"]["image"].rsplit(":", 1)[1] == runtime_tags["HAKU_CONSOLE_IMAGE_TAG"]
    assert containers["static"]["image"].rsplit(":", 1)[1] == runtime_tags["HAKU_CONSOLE_STATIC_IMAGE_TAG"]

    for marker in (
        '# {"$imagepolicy": "flux-system:haku-console"}',
        '# {"$imagepolicy": "flux-system:haku-console:tag"}',
        '# {"$imagepolicy": "flux-system:haku-console-static"}',
        '# {"$imagepolicy": "flux-system:haku-console-static:tag"}',
    ):
        assert raw.count(marker) == 1, f"missing or duplicated Flux marker: {marker}"


def test_haku_console_oauth_edge_contract(k8s_dir: Path) -> None:
    """Haku serves only on TLS, preserves one canonical origin, and emits HSTS at the edge."""
    route = yaml.safe_load((k8s_dir / "haku" / "console" / "httproute.yaml").read_text(encoding="utf-8"))
    assert route["spec"]["parentRefs"] == [
        {"name": "cluster-gateway", "namespace": "gateway-system", "sectionName": "https-wildcard"}
    ]
    assert route["spec"]["rules"][0]["filters"] == [
        {
            "type": "ResponseHeaderModifier",
            "responseHeaderModifier": {"set": [{"name": "Strict-Transport-Security", "value": "max-age=31536000"}]},
        }
    ]

    deployment = yaml.safe_load((k8s_dir / "haku" / "console" / "deployment.yaml").read_text(encoding="utf-8"))
    server = next(c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "server")
    literal_env = {entry["name"]: entry["value"] for entry in server["env"] if "value" in entry}
    assert literal_env["HAKU_CONSOLE_PUBLIC_BASE_URL"] == "https://haku.allegedly.works"
    assert "HAKU_CONSOLE_MCP_OAUTH__PUBLIC_BASE_URL" not in {entry["name"] for entry in server["env"]}


def test_retry_policy(cluster: ParsedCluster) -> None:
    check_retry_policy(cluster)


def test_no_orphaned_files(cluster: ParsedCluster, k8s_dir: Path) -> None:
    """All YAML files must be referenced by a kustomization.yaml."""
    errors = find_orphaned_files(cluster, k8s_dir)
    assert not errors, "\n".join(errors)


def test_no_unwired_flux_kustomizations(cluster: ParsedCluster, k8s_dir: Path) -> None:
    """Every flux-kustomization.yaml on disk must be referenced in the root kustomization."""
    on_disk = {f.resolve() for f in k8s_dir.rglob("flux-kustomization.yaml") if "flux-system" not in f.parts}

    root_kust = cluster.kustomize_files[k8s_dir / "kustomization.yaml"]
    referenced = {r for r in root_kust.resolved_resources if r.name == "flux-kustomization.yaml"}

    unwired = sorted(f.relative_to(k8s_dir) for f in on_disk - referenced)
    assert not unwired, "flux-kustomization.yaml files not listed in root kustomization.yaml:\n" + "\n".join(
        f"  {f}" for f in unwired
    )


def test_goldilocks_namespace_labels(cluster: ParsedCluster) -> None:
    """Namespaces with goldilocks vpa-update-mode must also have goldilocks enabled."""
    errors = check_goldilocks_namespace_labels(cluster)
    assert not errors, "\n".join(errors)


def test_goldilocks_explicit_decision(cluster: ParsedCluster) -> None:
    """Namespaces with workloads must explicitly set goldilocks enabled label."""
    errors = check_goldilocks_explicit_decision(cluster)
    assert not errors, "\n".join(errors)


def test_blueprint_completeness(k8s_dir: Path) -> None:
    """All authentik blueprint YAML files must be listed in configMapGenerator."""
    errors = check_blueprint_completeness(k8s_dir)
    assert not errors, "\n".join(errors)


def test_proxy_providers_assigned_to_outpost(k8s_dir: Path) -> None:
    """Every present authentik proxy provider must be assigned to an outpost.

    An unassigned proxy provider (HTTPRoute present, but not on the embedded outpost)
    302s to a login flow served on its own host, breaking Google SSO with
    redirect_uri_mismatch — the haku.allegedly.works failure mode.
    """
    errors = check_proxy_provider_outpost_assignment(k8s_dir)
    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    pytest_bazel.main()
