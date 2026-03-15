"""Test: flux kustomizations deploying HelmReleases/Terraform have healthChecks."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel

from cluster.scripts.validate_cluster.cluster import ParsedCluster
from cluster.scripts.validate_cluster.flux import FluxKustomization, HealthCheck
from cluster.scripts.validate_cluster.k8s import K8sResource
from cluster.scripts.validate_cluster.kustomize import KustomizeFile

pytest_plugins = ["cluster.scripts.validate_cluster.conftest"]

_HEALTH_CHECK_REQUIRED_KINDS = ["HelmRelease", "Terraform"]


def _kust_deploys_kind(kind: str, kust: KustomizeFile, source_resources: dict[Path, list[K8sResource]]) -> bool:
    return any(
        resource.kind == kind
        for resource_path in kust.resources
        if resource_path in source_resources
        for resource in source_resources[resource_path]
    )


def _check_controller_health_checks(cluster: ParsedCluster, k8s_dir: Path, workspace: Path) -> list[str]:
    return [
        f"{name}: deploys a {kind} but has no healthChecks for it. "
        f"Add healthChecks with kind: {kind} to {flux_kust.file_path.relative_to(k8s_dir)}."
        for name, flux_kust in cluster.flux_kustomizations.items()
        if flux_kust.spec_path
        if (kust_dir := (workspace / flux_kust.spec_path.removeprefix("./")))
        if (kust := cluster.kustomize_files.get(kust_dir / "kustomization.yaml"))
        for kind in _HEALTH_CHECK_REQUIRED_KINDS
        if _kust_deploys_kind(kind, kust, cluster.source_resources)
        if not any(hc.kind == kind for hc in flux_kust.health_checks)
    ]


# ============================================================================
# Integration test (real cluster data)
# ============================================================================


def test_controller_resources_have_health_checks(cluster: ParsedCluster, k8s_dir: Path, workspace: Path) -> None:
    errors = _check_controller_health_checks(cluster, k8s_dir, workspace)
    assert not errors, "\n".join(errors)


# ============================================================================
# Unit tests (synthetic data)
# ============================================================================


def _make_cluster(
    k8s_dir: Path,
    *,
    resource_kind: str = "HelmRelease",
    resource_api_version: str = "helm.toolkit.fluxcd.io/v2",
    health_check_kind: str | None = None,
) -> ParsedCluster:
    """Build a minimal ParsedCluster with one resource and optional healthCheck."""
    resource_file = k8s_dir / "test-app" / "resource.yaml"
    kust_file = k8s_dir / "test-app" / "kustomization.yaml"
    flux_file = k8s_dir / "test-app" / "flux-kustomization.yaml"

    return ParsedCluster(
        kustomize_files={kust_file: KustomizeFile(path=kust_file, resources=[resource_file])},
        flux_kustomizations={
            "test-app": FluxKustomization(
                name="test-app",
                file_path=flux_file,
                path="./cluster/k8s/test-app",
                healthChecks=[HealthCheck(kind=health_check_kind, name="test-app", namespace="test-app")]
                if health_check_kind
                else [],
            )
        },
        source_resources={resource_file: [K8sResource(kind=resource_kind, apiVersion=resource_api_version)]},
    )


class TestControllerResourceHealthChecks:
    @pytest.fixture
    def repo_root(self, tmp_path: Path) -> Path:
        (tmp_path / "cluster" / "k8s").mkdir(parents=True)
        return tmp_path

    @pytest.fixture
    def k8s_dir(self, repo_root: Path) -> Path:
        return repo_root / "cluster" / "k8s"

    @pytest.mark.parametrize(
        ("resource_kind", "resource_api_version", "health_check_kind"),
        [
            ("HelmRelease", "helm.toolkit.fluxcd.io/v2", "HelmRelease"),
            ("Terraform", "infra.contrib.fluxcd.io/v1alpha2", "Terraform"),
        ],
    )
    def test_no_error_with_matching_healthcheck(
        self, k8s_dir: Path, repo_root: Path, resource_kind: str, resource_api_version: str, health_check_kind: str
    ) -> None:
        cluster = _make_cluster(
            k8s_dir,
            resource_kind=resource_kind,
            resource_api_version=resource_api_version,
            health_check_kind=health_check_kind,
        )
        assert _check_controller_health_checks(cluster, k8s_dir, repo_root) == []

    @pytest.mark.parametrize(
        ("resource_kind", "resource_api_version"),
        [("HelmRelease", "helm.toolkit.fluxcd.io/v2"), ("Terraform", "infra.contrib.fluxcd.io/v1alpha2")],
    )
    def test_error_without_healthcheck(
        self, k8s_dir: Path, repo_root: Path, resource_kind: str, resource_api_version: str
    ) -> None:
        cluster = _make_cluster(k8s_dir, resource_kind=resource_kind, resource_api_version=resource_api_version)
        errors = _check_controller_health_checks(cluster, k8s_dir, repo_root)
        assert len(errors) == 1
        assert resource_kind in errors[0]

    def test_no_error_for_plain_resources(self, k8s_dir: Path, repo_root: Path) -> None:
        cluster = _make_cluster(k8s_dir, resource_kind="ConfigMap", resource_api_version="v1")
        assert _check_controller_health_checks(cluster, k8s_dir, repo_root) == []


if __name__ == "__main__":
    pytest_bazel.main()
