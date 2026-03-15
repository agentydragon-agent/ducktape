"""Test: Cilium Helm values files render without errors."""

from __future__ import annotations

import pytest_bazel

from cluster.validation.helm_templates import ensure_cilium_repo, validate_helm_template
from util.bazel.runfiles import get_required_path

_CILIUM_VALUES_RLOCATION = "_main/cluster/terraform/bootstrap/infrastructure/cilium-values.yaml"


def test_cilium_values_render() -> None:
    assert ensure_cilium_repo(), "Failed to add Cilium Helm repo"
    values_file = get_required_path(_CILIUM_VALUES_RLOCATION)
    success, error = validate_helm_template(values_file)
    assert success, f"Helm template failed for {values_file}: {error}"


if __name__ == "__main__":
    pytest_bazel.main()
