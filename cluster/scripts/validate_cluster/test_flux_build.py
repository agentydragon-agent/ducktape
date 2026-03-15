"""Test: flux build kustomization succeeds and produces expected resources."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel
import yaml

from cluster.scripts.validate_cluster.flux import run_flux_build
from cluster.scripts.validate_cluster.k8s import parse_k8s_resources

pytest_plugins = ["cluster.scripts.validate_cluster.conftest"]


def test_flux_build_succeeds(k8s_dir: Path) -> None:
    result = run_flux_build(k8s_dir)
    assert result.returncode == 0, f"flux build failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.stdout.strip(), f"flux build returned empty output:\nstderr: {result.stderr.strip() or 'none'}"

    resources = list(parse_k8s_resources(yaml.safe_load_all(result.stdout)))
    kinds = {r.kind for r in resources}
    assert "Kustomization" in kinds, "No Flux Kustomization resources in flux build output"
    assert "GitRepository" in kinds, "No GitRepository resource in flux build output"


if __name__ == "__main__":
    pytest_bazel.main()
