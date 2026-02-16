"""Tests for validate_kustomizations.py."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent

import pytest
import pytest_bazel
import yaml

from cluster.scripts.validate_kustomizations import (
    CRD_TO_OPERATOR,
    DependsOn,
    FluxKustomization,
    HealthCheck,
    K8sResource,
    KustomizeBuildResult,
    KustomizeFile,
    ParsedCluster,
    build_dependency_graph,
    check_crd_layering,
    check_helmrelease_health_checks,
    check_required_dependencies,
    find_cycles,
    parse_flux_kustomization,
    parse_k8s_resource,
)


def make_build_result(path: Path, yaml_output: str) -> KustomizeBuildResult:
    """Create a KustomizeBuildResult from YAML output."""
    resources = []
    for doc in yaml.safe_load_all(yaml_output):
        resource = parse_k8s_resource(doc)
        if resource:
            resources.append(resource)
    return KustomizeBuildResult(kustomization_path=path, success=True, resources=resources)


class TestCrdLayeringCheck:
    """Tests for CRD layering violation detection."""

    def test_valid_helmrelease_only(self) -> None:
        """HelmRelease without CRD instances is valid."""
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: test-app
            spec:
              chart:
                spec:
                  chart: test
        """)
        path = Path("/k8s/test-app/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_valid_crd_only(self) -> None:
        """ExternalSecret without HelmRelease is valid."""
        output = dedent("""
            apiVersion: external-secrets.io/v1beta1
            kind: ExternalSecret
            metadata:
              name: test-secret
            spec:
              secretStoreRef:
                name: vault-backend
        """)
        path = Path("/k8s/test-app/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_detects_crd_layering_violation(self) -> None:
        """HelmRelease mixed with ExternalSecret is a violation."""
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: test-app
            spec:
              chart:
                spec:
                  chart: test
            ---
            apiVersion: external-secrets.io/v1beta1
            kind: ExternalSecret
            metadata:
              name: test-secret
            spec:
              secretStoreRef:
                name: vault-backend
        """)
        path = Path("/k8s/test-app/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert len(errors) == 1
        assert "CRD layering violation" in errors[0]
        assert "ExternalSecret" in errors[0]

    def test_skips_operator_kustomizations(self) -> None:
        """Operator kustomizations are exempt from layering check."""
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: external-secrets
            ---
            apiVersion: external-secrets.io/v1beta1
            kind: ClusterSecretStore
            metadata:
              name: vault
        """)
        # external-secrets-operator is in OPERATOR_KUSTOMIZATIONS
        path = Path("/k8s/external-secrets-operator/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_skips_nested_operator_kustomizations(self) -> None:
        """Nested kustomizations under operator directories are exempt."""
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: cert-manager-webhook
            ---
            apiVersion: cert-manager.io/v1
            kind: ClusterIssuer
            metadata:
              name: letsencrypt-prod
        """)
        # cert-manager-config/base is nested under cert-manager-config which is in OPERATOR_KUSTOMIZATIONS
        path = Path("/k8s/cert-manager-config/base/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_skips_deeply_nested_operator_kustomizations(self) -> None:
        """Deeply nested kustomizations under operator directories are exempt."""
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: vault-webhook
            ---
            apiVersion: vault.banzaicloud.com/v1alpha1
            kind: Vault
            metadata:
              name: vault
        """)
        # vault/config/base is nested under vault which is in OPERATOR_KUSTOMIZATIONS
        path = Path("/k8s/vault/config/base/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_skips_overlay_directories(self) -> None:
        """Overlays are exempt - base handles the check."""
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: test-app
            ---
            apiVersion: external-secrets.io/v1beta1
            kind: ExternalSecret
            metadata:
              name: test-secret
        """)
        path = Path("/k8s/test-app/overlays/production/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []


class TestDependencyGraph:
    """Tests for dependency graph building and cycle detection."""

    def test_builds_graph_from_kustomizations(self) -> None:
        """Builds correct dependency graph."""
        kustomizations = {
            "app-a": FluxKustomization(
                name="app-a", file_path=Path("./k8s/app-a"), depends_on=[DependsOn(name="core")]
            ),
            "app-b": FluxKustomization(
                name="app-b",
                file_path=Path("./k8s/app-b"),
                depends_on=[DependsOn(name="core"), DependsOn(name="app-a")],
            ),
            "core": FluxKustomization(name="core", file_path=Path("./k8s/core"), depends_on=[]),
        }
        graph = build_dependency_graph(kustomizations)

        # core is depended on by app-a and app-b
        assert set(graph["core"]) == {"app-a", "app-b"}
        # app-a is depended on by app-b
        assert graph["app-a"] == ["app-b"]

    def test_detects_cycle(self) -> None:
        """Detects circular dependencies."""
        graph = {"a": ["b"], "b": ["a"]}
        all_nodes = {"a", "b"}
        cycles = find_cycles(graph, all_nodes)
        assert len(cycles) > 0
        # Cycle should contain both a and b
        cycle_nodes = set(cycles[0])
        assert "a" in cycle_nodes
        assert "b" in cycle_nodes

    def test_no_cycle_in_dag(self) -> None:
        """No false positives for valid DAGs."""
        graph = {"core": ["app-a", "app-b"], "app-a": ["app-b"]}
        all_nodes = {"core", "app-a", "app-b"}
        cycles = find_cycles(graph, all_nodes)
        assert cycles == []


class TestRequiredDependencies:
    """Tests for required dependency checking."""

    def test_detects_missing_dependency(self) -> None:
        """Detects when required dependency is missing."""
        # authentik should depend on external-secrets-config but doesn't
        kustomizations = {
            "authentik": FluxKustomization(name="authentik", file_path=Path("./k8s/authentik"), depends_on=[]),
            "external-secrets-config": FluxKustomization(
                name="external-secrets-config", file_path=Path("./k8s/external-secrets"), depends_on=[]
            ),
        }
        errors = check_required_dependencies(kustomizations)
        # Should have error about authentik missing external-secrets-config
        matching = [e for e in errors if "authentik" in e and "external-secrets-config" in e]
        assert len(matching) > 0

    def test_accepts_valid_dependencies(self) -> None:
        """No errors when required dependencies are present."""
        kustomizations = {
            "authentik": FluxKustomization(
                name="authentik",
                file_path=Path("./k8s/authentik"),
                depends_on=[DependsOn(name="external-secrets-config"), DependsOn(name="ingress-nginx")],
            ),
            "external-secrets-config": FluxKustomization(
                name="external-secrets-config",
                file_path=Path("./k8s/external-secrets"),
                depends_on=[DependsOn(name="vault")],
            ),
            "ingress-nginx": FluxKustomization(
                name="ingress-nginx", file_path=Path("./k8s/ingress-nginx"), depends_on=[DependsOn(name="cert-manager")]
            ),
            "vault": FluxKustomization(name="vault", file_path=Path("./k8s/vault"), depends_on=[]),
            "cert-manager": FluxKustomization(name="cert-manager", file_path=Path("./k8s/cert-manager"), depends_on=[]),
        }
        errors = check_required_dependencies(kustomizations)
        # Should have no errors about authentik
        authentik_errors = [e for e in errors if "authentik" in e]
        assert len(authentik_errors) == 0


class TestParseFluxKustomization:
    """Tests for parsing flux-kustomization.yaml files."""

    def test_parses_valid_kustomization(self, tmp_path: Path) -> None:
        """Parses flux-kustomization.yaml correctly."""
        kust_file = tmp_path / "flux-kustomization.yaml"
        kust_file.write_text(
            dedent("""
            apiVersion: kustomize.toolkit.fluxcd.io/v1
            kind: Kustomization
            metadata:
              name: test-app
              namespace: flux-system
            spec:
              interval: 10m
              path: ./k8s/test-app
              dependsOn:
                - name: core
        """)
        )
        kustomizations = parse_flux_kustomization(kust_file)
        assert len(kustomizations) == 1
        assert kustomizations[0].name == "test-app"
        assert len(kustomizations[0].depends_on) == 1
        assert kustomizations[0].depends_on[0].name == "core"

    def test_loads_cycle_testdata(self) -> None:
        """Loads cycle testdata and detects the cycle."""
        testdata_dir = Path(os.environ.get("TEST_SRCDIR", ".")) / "ducktape/cluster/scripts/testdata/cycle"
        if not testdata_dir.exists():
            pytest.skip("Testdata not available in this context")

        # Parse all flux-kustomization.yaml files in testdata
        kustomizations = {}
        for flux_file in testdata_dir.rglob("flux-kustomization.yaml"):
            for kust in parse_flux_kustomization(flux_file):
                kustomizations[kust.name] = kust

        # Build graph and check for cycles
        graph = build_dependency_graph(kustomizations)
        all_nodes = set(kustomizations.keys()) | set().union(*graph.values()) if graph else set(kustomizations.keys())
        cycles = find_cycles(graph, all_nodes)

        assert len(cycles) > 0, "Should detect cycle between cycle-a and cycle-b"


class TestCrdToOperatorMapping:
    """Tests for CRD to operator mapping completeness."""

    def test_common_crds_mapped(self) -> None:
        """Common CRDs are mapped to their operators."""
        assert CRD_TO_OPERATOR["ExternalSecret"] == "external-secrets-operator"
        assert CRD_TO_OPERATOR["Certificate"] == "cert-manager"
        assert CRD_TO_OPERATOR["ClusterPolicy"] == "kyverno"
        assert CRD_TO_OPERATOR["Terraform"] == "tofu-controller"


class TestParseK8sResource:
    """Tests for K8sResource parsing."""

    def test_parses_basic_resource(self) -> None:
        """Parses basic K8s resource."""
        doc = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "test-cm", "namespace": "default"}}
        resource = parse_k8s_resource(doc)
        assert resource is not None
        assert resource.kind == "ConfigMap"
        assert resource.api_version == "v1"
        assert resource.name == "test-cm"
        assert resource.namespace == "default"

    def test_parses_helmrelease_chart_version(self) -> None:
        """Parses HelmRelease with chart version."""
        doc = {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "metadata": {"name": "test-hr"},
            "spec": {"chart": {"spec": {"version": "1.2.3"}}},
        }
        resource = parse_k8s_resource(doc)
        assert resource is not None
        assert resource.kind == "HelmRelease"
        assert resource.chart_version == "1.2.3"

    def test_returns_none_for_empty_doc(self) -> None:
        """Returns None for empty document."""
        assert parse_k8s_resource({}) is None
        assert parse_k8s_resource(None) is None  # type: ignore[arg-type]

    def test_returns_none_for_missing_kind(self) -> None:
        """Returns None for document without kind."""
        doc = {"apiVersion": "v1", "metadata": {"name": "test"}}
        assert parse_k8s_resource(doc) is None


MakeCluster = Callable[..., ParsedCluster]


class TestHelmReleaseHealthChecks:
    """Tests for HelmRelease healthChecks validation."""

    @pytest.fixture
    def repo_root(self, tmp_path: Path) -> Path:
        (tmp_path / "cluster" / "k8s").mkdir(parents=True)
        return tmp_path

    @pytest.fixture
    def k8s_dir(self, repo_root: Path) -> Path:
        return repo_root / "cluster" / "k8s"

    @pytest.fixture
    def make_cluster(self, k8s_dir: Path) -> MakeCluster:
        def _make(*, has_healthcheck: bool, has_helmrelease: bool = True) -> ParsedCluster:
            hr_file = k8s_dir / "test-app" / "helmrelease.yaml"
            kust_file = k8s_dir / "test-app" / "kustomization.yaml"
            flux_file = k8s_dir / "test-app" / "flux-kustomization.yaml"

            return ParsedCluster(
                kustomize_files={kust_file: KustomizeFile(path=kust_file, resources=[hr_file])},
                flux_kustomizations={
                    "test-app": FluxKustomization(
                        name="test-app",
                        file_path=flux_file,
                        path="./cluster/k8s/test-app",
                        healthChecks=[HealthCheck(kind="HelmRelease", name="test-app", namespace="test-app")]
                        if has_healthcheck
                        else [],
                    )
                },
                source_resources={hr_file: [K8sResource(kind="HelmRelease", apiVersion="helm.toolkit.fluxcd.io/v2")]}
                if has_helmrelease
                else {},
            )

        return _make

    def test_no_error_with_healthcheck(self, k8s_dir: Path, repo_root: Path, make_cluster: MakeCluster) -> None:
        """Kustomization with HelmRelease and healthChecks passes."""
        cluster = make_cluster(has_healthcheck=True)
        assert check_helmrelease_health_checks(cluster, k8s_dir, repo_root) == []

    def test_error_without_healthcheck(self, k8s_dir: Path, repo_root: Path, make_cluster: MakeCluster) -> None:
        """Kustomization with HelmRelease but no healthChecks reports error."""
        errors = check_helmrelease_health_checks(make_cluster(has_healthcheck=False), k8s_dir, repo_root)
        assert len(errors) == 1
        assert "test-app" in errors[0]
        assert "healthChecks" in errors[0]

    def test_no_error_without_helmrelease(self, k8s_dir: Path, repo_root: Path, make_cluster: MakeCluster) -> None:
        """Kustomization without HelmRelease does not trigger error."""
        cluster = make_cluster(has_healthcheck=False, has_helmrelease=False)
        assert check_helmrelease_health_checks(cluster, k8s_dir, repo_root) == []


if __name__ == "__main__":
    pytest_bazel.main()
