"""Shared fixtures for cluster validation tests.

Pure-analysis tests resolve cluster/k8s/ from runfiles (data deps).
Kustomize-dependent tests load pre-built results from a JSON file (genrule output).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter

from cluster.scripts.validate_cluster.cluster import ParsedCluster, parse_cluster
from cluster.scripts.validate_cluster.kustomize import KustomizeBuildResult
from util.bazel.runfiles import get_required_path

_K8S_ROOT_KUSTOMIZATION = "_main/cluster/k8s/kustomization.yaml"
_KUSTOMIZE_RESULTS_RLOCATION = "_main/cluster/scripts/validate_cluster/kustomize_build_results.json"


@pytest.fixture(scope="session")
def workspace() -> Path:
    """Repo root within runfiles (parent of cluster/k8s)."""
    return get_required_path(_K8S_ROOT_KUSTOMIZATION).parent.parent.parent


@pytest.fixture(scope="session")
def k8s_dir() -> Path:
    return get_required_path(_K8S_ROOT_KUSTOMIZATION).parent


@pytest.fixture(scope="session")
def cluster(k8s_dir: Path) -> ParsedCluster:
    return parse_cluster(k8s_dir)


@pytest.fixture(scope="session")
def kustomize_build_results() -> list[KustomizeBuildResult]:
    """Load pre-built kustomize results from genrule output."""
    results_path = get_required_path(_KUSTOMIZE_RESULTS_RLOCATION)
    adapter = TypeAdapter(list[KustomizeBuildResult])
    return adapter.validate_json(results_path.read_bytes())
