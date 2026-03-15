"""Test: flux kustomizations deploying HelmReleases/Terraform have healthChecks."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from cluster.scripts.validate_cluster.cluster import ParsedCluster
from cluster.scripts.validate_cluster.k8s import K8sResource
from cluster.scripts.validate_cluster.kustomize import KustomizeFile

_HEALTH_CHECK_REQUIRED_KINDS = ["HelmRelease", "Terraform"]


def _kust_deploys_kind(kind: str, kust: KustomizeFile, source_resources: dict[Path, list[K8sResource]]) -> bool:
    return any(
        resource.kind == kind
        for resource_path in kust.resources
        for resource in source_resources.get(resource_path, [])
    )


def test_controller_resources_have_health_checks(cluster: ParsedCluster, k8s_dir: Path, workspace: Path) -> None:
    errors = [
        f"{name}: deploys a {kind} but has no healthChecks for it. "
        f"Add healthChecks with kind: {kind} to {flux_kust.file_path.relative_to(k8s_dir)}."
        for name, flux_kust in cluster.flux_kustomizations.items()
        if flux_kust.spec_path
        if (kust_dir := (workspace / flux_kust.spec_path.removeprefix("./")).resolve())
        if (kust := cluster.kustomize_files.get(kust_dir / "kustomization.yaml"))
        for kind in _HEALTH_CHECK_REQUIRED_KINDS
        if _kust_deploys_kind(kind, kust, cluster.source_resources)
        if not any(hc.kind == kind for hc in flux_kust.health_checks)
    ]
    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    pytest_bazel.main()
