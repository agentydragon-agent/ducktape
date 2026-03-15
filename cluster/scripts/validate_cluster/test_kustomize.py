"""Tests that require kustomize build output.

All kustomize-dependent checks are combined in one test target so the
genrule runs once. Individual checks are separate test functions for
clear failure reporting.

Note: kustomize build failures are caught by the genrule itself (exits non-zero),
so there's no need for a separate "all kustomizations build" test.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import more_itertools
import pytest_bazel
import yaml

from cluster.scripts.validate_cluster.checks import CRD_TO_OPERATOR, OPERATOR_KUSTOMIZATIONS
from cluster.scripts.validate_cluster.k8s import parse_k8s_resources
from cluster.scripts.validate_cluster.kustomize import KustomizeBuildResult

pytest_plugins = ["cluster.scripts.validate_cluster.conftest"]


def _check_crd_layering(result: KustomizeBuildResult) -> list[str]:
    """Check if a kustomization mixes HelmReleases with CRD instances."""
    if not result.success:
        return []

    if any(part in OPERATOR_KUSTOMIZATIONS for part in result.kustomization_path.parent.parts):
        return []

    if "overlays" in result.kustomization_path.parts:
        return []

    has_helmrelease = any(r.kind == "HelmRelease" for r in result.resources)
    crd_instances = [(r.kind, CRD_TO_OPERATOR[r.kind]) for r in result.resources if r.kind in CRD_TO_OPERATOR]

    if has_helmrelease and crd_instances:
        kust_name = result.kustomization_path.parent.name
        unique_crds = sorted({f"{k} (needs {op})" for k, op in crd_instances})
        return [
            f"{kust_name}: mixes HelmRelease with CRD instances: {', '.join(unique_crds)}. "
            f"Split into a separate '{kust_name}-secrets/' Kustomization."
        ]

    return []


def _make_build_result(path: Path, yaml_output: str) -> KustomizeBuildResult:
    return KustomizeBuildResult(
        kustomization_path=path, success=True, resources=parse_k8s_resources(yaml.safe_load_all(yaml_output))
    )


# ============================================================================
# Integration tests (real cluster data)
# ============================================================================


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
        errors.extend(_check_crd_layering(result))
    assert not errors, "\n".join(errors)


# ============================================================================
# Unit tests (synthetic data)
# ============================================================================


class TestCrdLayeringCheck:
    def test_valid_helmrelease_only(self) -> None:
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: test-app
            spec:
              chart:
                spec:
                  chart: test
        """)
        assert _check_crd_layering(_make_build_result(Path("/k8s/test-app/kustomization.yaml"), output)) == []

    def test_valid_crd_only(self) -> None:
        output = dedent("""
            apiVersion: external-secrets.io/v1beta1
            kind: ExternalSecret
            metadata:
              name: test-secret
            spec:
              secretStoreRef:
                name: vault-backend
        """)
        assert _check_crd_layering(_make_build_result(Path("/k8s/test-app/kustomization.yaml"), output)) == []

    def test_detects_crd_layering_violation(self) -> None:
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: test-app
            spec:
              chart:
                spec:
                  chart: test
            ---
            apiVersion: external-secrets.io/v1beta1
            kind: ExternalSecret
            metadata:
              name: test-secret
            spec:
              secretStoreRef:
                name: vault-backend
        """)
        errors = _check_crd_layering(_make_build_result(Path("/k8s/test-app/kustomization.yaml"), output))
        assert len(errors) == 1
        assert "ExternalSecret" in errors[0]

    def test_skips_operator_kustomizations(self) -> None:
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: external-secrets
            ---
            apiVersion: external-secrets.io/v1beta1
            kind: ClusterSecretStore
            metadata:
              name: vault
        """)
        assert (
            _check_crd_layering(_make_build_result(Path("/k8s/external-secrets-operator/kustomization.yaml"), output))
            == []
        )

    def test_skips_nested_operator_kustomizations(self) -> None:
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: cert-manager-webhook
            ---
            apiVersion: cert-manager.io/v1
            kind: ClusterIssuer
            metadata:
              name: letsencrypt-prod
        """)
        assert (
            _check_crd_layering(_make_build_result(Path("/k8s/cert-manager-config/base/kustomization.yaml"), output))
            == []
        )

    def test_skips_deeply_nested_operator_kustomizations(self) -> None:
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: vault-webhook
            ---
            apiVersion: vault.banzaicloud.com/v1alpha1
            kind: Vault
            metadata:
              name: vault
        """)
        assert _check_crd_layering(_make_build_result(Path("/k8s/vault/config/base/kustomization.yaml"), output)) == []

    def test_skips_overlay_directories(self) -> None:
        output = dedent("""
            apiVersion: helm.toolkit.fluxcd.io/v2
            kind: HelmRelease
            metadata:
              name: test-app
            ---
            apiVersion: external-secrets.io/v1beta1
            kind: ExternalSecret
            metadata:
              name: test-secret
        """)
        assert (
            _check_crd_layering(
                _make_build_result(Path("/k8s/test-app/overlays/production/kustomization.yaml"), output)
            )
            == []
        )


class TestCrdToOperatorMapping:
    def test_common_crds_mapped(self) -> None:
        assert CRD_TO_OPERATOR["ExternalSecret"] == "external-secrets-operator"
        assert CRD_TO_OPERATOR["Certificate"] == "cert-manager"
        assert CRD_TO_OPERATOR["ClusterPolicy"] == "kyverno"
        assert CRD_TO_OPERATOR["Terraform"] == "tofu-controller"


if __name__ == "__main__":
    pytest_bazel.main()
