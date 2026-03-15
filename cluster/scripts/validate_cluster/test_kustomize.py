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

from cluster.scripts.validate_cluster.checks import CRD_TO_OPERATOR, OPERATOR_KUSTOMIZATIONS
from cluster.scripts.validate_cluster.kustomize import KustomizeBuildResult


def test_no_duplicate_external_secrets(kustomize_build_results: list[KustomizeBuildResult]) -> None:
    """Exactly one external-secrets HelmRelease must exist."""
    deployments: dict[str, list[str]] = {}
    for result in kustomize_build_results:
        for resource in result.resources:
            if resource.kind == "HelmRelease" and resource.name == "external-secrets":
                key = f"{resource.namespace}/{resource.chart_version or 'unknown'}"
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
        if any(part in OPERATOR_KUSTOMIZATIONS for part in result.kustomization_path.parent.parts):
            continue
        if "overlays" in result.kustomization_path.parts:
            continue

        has_helmrelease = any(r.kind == "HelmRelease" for r in result.resources)
        crd_instances = [(r.kind, CRD_TO_OPERATOR[r.kind]) for r in result.resources if r.kind in CRD_TO_OPERATOR]

        if has_helmrelease and crd_instances:
            kust_name = result.kustomization_path.parent.name
            unique_crds = sorted({f"{k} (needs {op})" for k, op in crd_instances})
            errors.append(
                f"{kust_name}: mixes HelmRelease with CRD instances: {', '.join(unique_crds)}. "
                f"Split into a separate '{kust_name}-secrets/' Kustomization."
            )
    assert not errors, "\n".join(errors)


if __name__ == "__main__":
    pytest_bazel.main()
