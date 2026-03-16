"""Tests that require kustomize build output.

All kustomize-dependent checks are combined in one test target so the
genrule runs once. Individual checks are separate test functions for
clear failure reporting.

Note: kustomize build failures are caught by the genrule itself (exits non-zero),
so there's no need for a separate "all kustomizations build" test.
"""

from __future__ import annotations

from pathlib import Path

import more_itertools
import pytest
import pytest_bazel
from pydantic import TypeAdapter

from cluster.validation.crd_layering import check_crd_layering
from cluster.validation.kustomize import KustomizeBuildResult
from util.bazel.runfiles import get_required_path

_RESULTS = TypeAdapter(list[KustomizeBuildResult]).validate_json(
    get_required_path("_main/cluster/validation/kustomize_build_results.json").read_bytes()
)


def test_no_duplicate_external_secrets() -> None:
    """Exactly one external-secrets HelmRelease must exist."""
    deployments: dict[tuple[str | None, str | None], list[Path]] = {}
    for result in _RESULTS:
        for resource in result.resources:
            if resource.kind == "HelmRelease" and resource.name == "external-secrets":
                key = (resource.namespace, resource.chart_version)
                deployments.setdefault(key, []).append(result.kustomization_path.parent)

    more_itertools.one(
        deployments,
        too_short=ValueError("No external-secrets HelmRelease found"),
        too_long=ValueError(
            "Multiple external-secrets HelmRelease found: " + ", ".join(f"{k}: {v}" for k, v in deployments.items())
        ),
    )


@pytest.mark.parametrize("result", _RESULTS, ids=lambda r: str(r.kustomization_path.parent))
def test_no_crd_layering_violations(result: KustomizeBuildResult) -> None:
    """HelmReleases must not be mixed with CRD instances in one kustomization."""
    errors = check_crd_layering(result)
    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    pytest_bazel.main()
