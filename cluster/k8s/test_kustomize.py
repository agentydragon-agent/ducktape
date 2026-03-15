"""Tests that require kustomize build output.

All kustomize-dependent checks are combined in one test target so the
genrule runs once. Individual checks are separate test functions for
clear failure reporting.

Note: kustomize build failures are caught by the genrule itself (exits non-zero),
so there's no need for a separate "all kustomizations build" test.
"""

from __future__ import annotations

import more_itertools
import pytest_bazel

from cluster.validation.crd_layering import check_crd_layering
from cluster.validation.kustomize import KustomizeBuildResult


def test_no_duplicate_external_secrets(kustomize_build_results: list[KustomizeBuildResult]) -> None:
    """Exactly one external-secrets HelmRelease must exist."""
    deployments: dict[tuple[str | None, str | None], list[str]] = {}
    for result in kustomize_build_results:
        for resource in result.resources:
            if resource.kind == "HelmRelease" and resource.name == "external-secrets":
                key = (resource.namespace, resource.chart_version)
                deployments.setdefault(key, []).append(str(result.kustomization_path.parent))

    more_itertools.one(
        deployments,
        too_short=ValueError("No external-secrets HelmRelease found"),
        too_long=ValueError(
            "Multiple external-secrets HelmRelease found: " + ", ".join(f"{k}: {v}" for k, v in deployments.items())
        ),
    )


def test_no_crd_layering_violations(kustomize_build_results: list[KustomizeBuildResult]) -> None:
    """HelmReleases must not be mixed with CRD instances in one kustomization."""
    errors = []
    for result in kustomize_build_results:
        errors.extend(check_crd_layering(result))
    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    pytest_bazel.main()
