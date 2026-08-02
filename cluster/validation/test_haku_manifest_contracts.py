"""Focused contracts over Haku's deployed Kubernetes manifests."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel
import yaml

from util.bazel.runfiles import get_required_path

_K8S_ROOT_KUSTOMIZATION = "_main/cluster/k8s/kustomization.yaml"


@pytest.fixture(scope="session")
def k8s_dir() -> Path:
    return get_required_path(_K8S_ROOT_KUSTOMIZATION).parent


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

    claude_egress_path = k8s_dir / "agents/haku-egress-proxy/ccnp-haku-claude-sandbox-egress.yaml"
    claude_egress_text = claude_egress_path.read_text()
    assert "haku-claude-sandbox" in claude_egress_text
    assert "haku-claude-oauth-proxy" in claude_egress_text

    service = yaml.safe_load((k8s_dir / "haku/console/service.yaml").read_text())
    bridge_service_port = next(port for port in service["spec"]["ports"] if port["port"] == 9090)
    deployment = yaml.safe_load((k8s_dir / "haku/console/deployment.yaml").read_text())
    server = next(
        container for container in deployment["spec"]["template"]["spec"]["containers"] if container["name"] == "server"
    )
    bridge_target_port = next(
        port["containerPort"] for port in server["ports"] if port["name"] == bridge_service_port["targetPort"]
    )
    claude_egress = yaml.safe_load(claude_egress_text)
    console_rule = next(
        rule
        for rule in claude_egress["spec"]["egress"]
        if rule.get("toEndpoints", [{}])[0].get("matchLabels", {}).get("k8s:app.kubernetes.io/name") == "haku-console"
    )
    assert console_rule["toPorts"][0]["ports"] == [{"port": str(bridge_target_port), "protocol": "TCP"}]

    general_injection = (k8s_dir / "kyverno/policies/inject-haku-egress-proxy.yaml").read_text()
    assert "haku-claude-sandbox" not in general_injection

    console_config = yaml.safe_load((k8s_dir / "haku/console/config.yaml").read_text())
    assert console_config["claude_runtime"] == {
        "namespace": "haku-claude-sandbox",
        "warm_pool": "haku-claude",
        "cwd": "/workspace",
        "session_ttl_seconds": 7200,
        "oauth_placeholder": "sk-ant-oat01-proxy-haku-claude-placeholder",
        "https_proxy": "http://haku-claude-oauth-proxy.haku-egress-proxy.svc.cluster.local:8180",
        "ca_bundle": "/egress-proxy-ca/ca-certificates.crt",
        "no_proxy": "127.0.0.1,localhost,.svc,.svc.cluster.local,kubernetes.default.svc,10.0.0.0/8",
        "mcp_url": "http://haku-console.haku-console.svc.cluster.local:9090/mcp",
        "mcp_static_agent_id": "8d5b0cba-a9ab-4c93-8c31-70d5c7af45c2",
    }
    mcp_agent = next(
        agent
        for agent in console_config["static_agents"]
        if agent["agent_id"] == console_config["claude_runtime"]["mcp_static_agent_id"]
    )
    assert mcp_agent["display_name"] == "Haku"
    assert mcp_agent["auto_approval_policy"] == "haku_v1"
    env_names = {entry["name"] for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert not any(name.startswith("HAKU_CONSOLE_CLAUDE_RUNTIME__") for name in env_names)


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


if __name__ == "__main__":
    pytest_bazel.main()
