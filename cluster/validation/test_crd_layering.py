"""Unit tests for CRD layering validation."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import pytest_bazel
import yaml

from cluster.validation.crd_layering import CrdLayeringViolation, check_crd_layering
from cluster.validation.k8s import parse_k8s_resources
from cluster.validation.kustomize import KustomizeBuildResult


def _build_result(path: Path, yaml_output: str) -> KustomizeBuildResult:
    return KustomizeBuildResult(
        kustomization_path=path, resources=parse_k8s_resources(yaml.safe_load_all(yaml_output))
    )


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
        check_crd_layering(_build_result(Path("/k8s/test-app/kustomization.yaml"), output))

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
        check_crd_layering(_build_result(Path("/k8s/test-app/kustomization.yaml"), output))

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
        with pytest.raises(CrdLayeringViolation, match="ExternalSecret"):
            check_crd_layering(_build_result(Path("/k8s/test-app/kustomization.yaml"), output))

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
        check_crd_layering(
            _build_result(Path("/k8s/external-secrets-operator/kustomization.yaml"), output)
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
        check_crd_layering(
            _build_result(Path("/k8s/cert-manager-config/base/kustomization.yaml"), output)
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
        check_crd_layering(_build_result(Path("/k8s/vault/config/base/kustomization.yaml"), output))

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
        check_crd_layering(
            _build_result(Path("/k8s/test-app/overlays/production/kustomization.yaml"), output)
        )


if __name__ == "__main__":
    pytest_bazel.main()
