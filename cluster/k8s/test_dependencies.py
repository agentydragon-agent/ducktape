"""Test: no dependency errors in the real cluster flux kustomizations."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from cluster.validation.cluster import ParsedCluster
from cluster.validation.dependencies import validate_dependencies


def test_no_dependency_errors(cluster: ParsedCluster, k8s_dir: Path) -> None:
    errors = validate_dependencies(cluster, k8s_dir)
    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    pytest_bazel.main()
