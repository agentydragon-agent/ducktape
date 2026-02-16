"""Tests for dependency graph and rule checking."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from cluster.scripts.validate_cluster.dependencies import (
    build_dependency_graph,
    check_required_dependencies,
    find_cycles,
)
from cluster.scripts.validate_cluster.flux import DependsOn, FluxKustomization


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

        assert set(graph["core"]) == {"app-a", "app-b"}
        assert graph["app-a"] == ["app-b"]

    def test_detects_cycle(self) -> None:
        """Detects circular dependencies."""
        graph = {"a": ["b"], "b": ["a"]}
        all_nodes = {"a", "b"}
        cycles = find_cycles(graph, all_nodes)
        assert len(cycles) > 0
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
        kustomizations = {
            "authentik": FluxKustomization(name="authentik", file_path=Path("./k8s/authentik"), depends_on=[]),
            "external-secrets-config": FluxKustomization(
                name="external-secrets-config", file_path=Path("./k8s/external-secrets"), depends_on=[]
            ),
        }
        errors = check_required_dependencies(kustomizations)
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
        authentik_errors = [e for e in errors if "authentik" in e]
        assert len(authentik_errors) == 0


if __name__ == "__main__":
    pytest_bazel.main()
