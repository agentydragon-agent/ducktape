"""Live test: no circular dependencies, required dependencies present."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from cluster.scripts.validate_cluster.cluster import ParsedCluster
from cluster.scripts.validate_cluster.dependencies import validate_dependencies

pytest_plugins = ["cluster.scripts.validate_cluster.live_conftest"]


def test_no_dependency_errors(cluster: ParsedCluster, k8s_dir: Path) -> None:
    errors = validate_dependencies(cluster, k8s_dir)
    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    pytest_bazel.main()
