"""Test: flux kustomizations deploying HelmReleases/Terraform have healthChecks."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from cluster.validation.cluster import ParsedCluster
from cluster.validation.health_checks import check_controller_health_checks


def test_controller_resources_have_health_checks(cluster: ParsedCluster, k8s_dir: Path, workspace: Path) -> None:
    errors = check_controller_health_checks(cluster, k8s_dir, workspace)
    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    pytest_bazel.main()
