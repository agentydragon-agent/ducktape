"""Tests for validate_kustomizations.py."""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest
import pytest_bazel

from cluster.scripts.validate_kustomizations import (
    CRD_TO_OPERATOR,
    DependsOn,
    KustomizationSpec,
    build_dependency_graph,
    check_crd_layering,
    check_required_dependencies,
    find_cycles,
    load_kustomizations,
)


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
        errors = check_crd_layering(path, output)
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
        errors = check_crd_layering(path, output)
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
        errors = check_crd_layering(path, output)
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
        errors = check_crd_layering(path, output)
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
              name: letsencrypt
        """)
        # cert-manager-config/base is nested under cert-manager-config which is in OPERATOR_KUSTOMIZATIONS
        path = Path("/k8s/cert-manager-config/base/kustomization.yaml")
        errors = check_crd_layering(path, output)
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
        errors = check_crd_layering(path, output)
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
        errors = check_crd_layering(path, output)
        assert errors == []


class TestDependencyGraph:
    """Tests for dependency graph building and cycle detection."""

    def test_builds_graph_from_kustomizations(self) -> None:
        """Builds correct dependency graph."""
        kustomizations = {
            "app-a": KustomizationSpec(path="./k8s/app-a", depends_on=[DependsOn(name="core")]),
            "app-b": KustomizationSpec(
                path="./k8s/app-b", depends_on=[DependsOn(name="core"), DependsOn(name="app-a")]
            ),
            "core": KustomizationSpec(path="./k8s/core", depends_on=[]),
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
            "authentik": KustomizationSpec(path="./k8s/authentik", depends_on=[]),
            "external-secrets-config": KustomizationSpec(path="./k8s/external-secrets", depends_on=[]),
        }
        errors = check_required_dependencies(kustomizations)
        # Should have error about authentik missing external-secrets-config
        matching = [e for e in errors if "authentik" in e and "external-secrets-config" in e]
        assert len(matching) > 0

    def test_accepts_valid_dependencies(self) -> None:
        """No errors when required dependencies are present."""
        kustomizations = {
            "authentik": KustomizationSpec(
                path="./k8s/authentik",
                depends_on=[DependsOn(name="external-secrets-config"), DependsOn(name="ingress-nginx")],
            ),
            "external-secrets-config": KustomizationSpec(
                path="./k8s/external-secrets", depends_on=[DependsOn(name="vault")]
            ),
            "ingress-nginx": KustomizationSpec(
                path="./k8s/ingress-nginx",
                depends_on=[DependsOn(name="cert-manager"), DependsOn(name="metallb-config")],
            ),
            "vault": KustomizationSpec(path="./k8s/vault", depends_on=[]),
            "cert-manager": KustomizationSpec(path="./k8s/cert-manager", depends_on=[]),
            "metallb-config": KustomizationSpec(path="./k8s/metallb-config", depends_on=[]),
        }
        errors = check_required_dependencies(kustomizations)
        # Should have no errors about authentik
        authentik_errors = [e for e in errors if "authentik" in e]
        assert len(authentik_errors) == 0


class TestLoadKustomizations:
    """Tests for loading kustomizations from testdata."""

    def test_loads_valid_kustomization(self, tmp_path: Path) -> None:
        """Loads flux-kustomization.yaml correctly."""
        kust_dir = tmp_path / "test-app"
        kust_dir.mkdir()
        (kust_dir / "flux-kustomization.yaml").write_text(
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
        kustomizations = load_kustomizations(tmp_path)
        assert "test-app" in kustomizations
        assert len(kustomizations["test-app"].depends_on) == 1
        assert kustomizations["test-app"].depends_on[0].name == "core"

    def test_loads_cycle_testdata(self) -> None:
        """Loads cycle testdata and detects the cycle."""
        testdata_dir = Path(os.environ.get("TEST_SRCDIR", ".")) / "ducktape/cluster/scripts/testdata/cycle"
        if not testdata_dir.exists():
            pytest.skip("Testdata not available in this context")

        kustomizations = load_kustomizations(testdata_dir)

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
        assert CRD_TO_OPERATOR["IPAddressPool"] == "metallb"
        assert CRD_TO_OPERATOR["Terraform"] == "core"


if __name__ == "__main__":
    pytest_bazel.main()
