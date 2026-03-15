"""Unit tests for CRD layering validation."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest_bazel

from cluster.validation.crd_layering import check_crd_layering, make_build_result


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
        assert check_crd_layering(make_build_result(Path("/k8s/test-app/kustomization.yaml"), output)) == []

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
        assert check_crd_layering(make_build_result(Path("/k8s/test-app/kustomization.yaml"), output)) == []

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
        errors = check_crd_layering(make_build_result(Path("/k8s/test-app/kustomization.yaml"), output))
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
            check_crd_layering(make_build_result(Path("/k8s/external-secrets-operator/kustomization.yaml"), output))
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
            check_crd_layering(make_build_result(Path("/k8s/cert-manager-config/base/kustomization.yaml"), output))
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
        assert check_crd_layering(make_build_result(Path("/k8s/vault/config/base/kustomization.yaml"), output)) == []

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
            check_crd_layering(make_build_result(Path("/k8s/test-app/overlays/production/kustomization.yaml"), output))
            == []
        )


if __name__ == "__main__":
    pytest_bazel.main()
