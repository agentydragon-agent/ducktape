"""Tests for non-graph validation checks."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import pytest_bazel
import yaml

from cluster.scripts.validate_cluster.checks import (
    CRD_TO_OPERATOR,
    check_blueprint_completeness,
    check_controller_resource_health_checks,
    check_crd_layering,
)
from cluster.scripts.validate_cluster.cluster import ParsedCluster
from cluster.scripts.validate_cluster.flux import FluxKustomization, HealthCheck
from cluster.scripts.validate_cluster.k8s import K8sResource, parse_k8s_resources
from cluster.scripts.validate_cluster.kustomize import KustomizeBuildResult, KustomizeFile


def make_build_result(path: Path, yaml_output: str) -> KustomizeBuildResult:
    """Create a KustomizeBuildResult from YAML output."""
    return KustomizeBuildResult(
        kustomization_path=path, success=True, resources=parse_k8s_resources(yaml.safe_load_all(yaml_output))
    )


class TestCrdLayeringCheck:
    """Tests for CRD layering violation detection."""

    def test_valid_helmrelease_only(self) -> None:
        """HelmRelease without CRD instances is valid."""
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
        path = Path("/k8s/test-app/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_valid_crd_only(self) -> None:
        """ExternalSecret without HelmRelease is valid."""
        output = dedent("""
            apiVersion: external-secrets.io/v1beta1
            kind: ExternalSecret
            metadata:
              name: test-secret
            spec:
              secretStoreRef:
                name: vault-backend
        """)
        path = Path("/k8s/test-app/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_detects_crd_layering_violation(self) -> None:
        """HelmRelease mixed with ExternalSecret is a violation."""
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
        path = Path("/k8s/test-app/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert len(errors) == 1
        assert "CRD layering violation" in errors[0]
        assert "ExternalSecret" in errors[0]

    def test_skips_operator_kustomizations(self) -> None:
        """Operator kustomizations are exempt from layering check."""
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
        path = Path("/k8s/external-secrets-operator/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_skips_nested_operator_kustomizations(self) -> None:
        """Nested kustomizations under operator directories are exempt."""
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
        path = Path("/k8s/cert-manager-config/base/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_skips_deeply_nested_operator_kustomizations(self) -> None:
        """Deeply nested kustomizations under operator directories are exempt."""
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
        path = Path("/k8s/vault/config/base/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []

    def test_skips_overlay_directories(self) -> None:
        """Overlays are exempt - base handles the check."""
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
        path = Path("/k8s/test-app/overlays/production/kustomization.yaml")
        result = make_build_result(path, output)
        errors = check_crd_layering(result)
        assert errors == []


class TestCrdToOperatorMapping:
    """Tests for CRD to operator mapping completeness."""

    def test_common_crds_mapped(self) -> None:
        """Common CRDs are mapped to their operators."""
        assert CRD_TO_OPERATOR["ExternalSecret"] == "external-secrets-operator"
        assert CRD_TO_OPERATOR["Certificate"] == "cert-manager"
        assert CRD_TO_OPERATOR["ClusterPolicy"] == "kyverno"
        assert CRD_TO_OPERATOR["Terraform"] == "tofu-controller"


def _make_cluster(
    k8s_dir: Path,
    *,
    resource_kind: str = "HelmRelease",
    resource_api_version: str = "helm.toolkit.fluxcd.io/v2",
    health_check_kind: str | None = None,
) -> ParsedCluster:
    """Build a minimal ParsedCluster with one resource and optional healthCheck."""
    resource_file = k8s_dir / "test-app" / "resource.yaml"
    kust_file = k8s_dir / "test-app" / "kustomization.yaml"
    flux_file = k8s_dir / "test-app" / "flux-kustomization.yaml"

    return ParsedCluster(
        kustomize_files={kust_file: KustomizeFile(path=kust_file, resources=[resource_file])},
        flux_kustomizations={
            "test-app": FluxKustomization(
                name="test-app",
                file_path=flux_file,
                path="./cluster/k8s/test-app",
                healthChecks=[HealthCheck(kind=health_check_kind, name="test-app", namespace="test-app")]
                if health_check_kind
                else [],
            )
        },
        source_resources={resource_file: [K8sResource(kind=resource_kind, apiVersion=resource_api_version)]},
    )


class TestControllerResourceHealthChecks:
    """Tests for controller resource (HelmRelease, Terraform) healthChecks validation."""

    @pytest.fixture
    def repo_root(self, tmp_path: Path) -> Path:
        (tmp_path / "cluster" / "k8s").mkdir(parents=True)
        return tmp_path

    @pytest.fixture
    def k8s_dir(self, repo_root: Path) -> Path:
        return repo_root / "cluster" / "k8s"

    @pytest.mark.parametrize(
        ("resource_kind", "resource_api_version", "health_check_kind"),
        [
            ("HelmRelease", "helm.toolkit.fluxcd.io/v2", "HelmRelease"),
            ("Terraform", "infra.contrib.fluxcd.io/v1alpha2", "Terraform"),
        ],
    )
    def test_no_error_with_matching_healthcheck(
        self, k8s_dir: Path, repo_root: Path, resource_kind: str, resource_api_version: str, health_check_kind: str
    ) -> None:
        """Controller resource with matching healthCheck passes."""
        cluster = _make_cluster(
            k8s_dir,
            resource_kind=resource_kind,
            resource_api_version=resource_api_version,
            health_check_kind=health_check_kind,
        )
        assert check_controller_resource_health_checks(cluster, k8s_dir, repo_root) == []

    @pytest.mark.parametrize(
        ("resource_kind", "resource_api_version"),
        [("HelmRelease", "helm.toolkit.fluxcd.io/v2"), ("Terraform", "infra.contrib.fluxcd.io/v1alpha2")],
    )
    def test_error_without_healthcheck(
        self, k8s_dir: Path, repo_root: Path, resource_kind: str, resource_api_version: str
    ) -> None:
        """Controller resource without healthCheck reports error."""
        cluster = _make_cluster(k8s_dir, resource_kind=resource_kind, resource_api_version=resource_api_version)
        errors = check_controller_resource_health_checks(cluster, k8s_dir, repo_root)
        assert len(errors) == 1
        assert resource_kind in errors[0]

    def test_no_error_for_plain_resources(self, k8s_dir: Path, repo_root: Path) -> None:
        """Kustomization with only plain resources (ConfigMap, etc.) needs no healthCheck."""
        cluster = _make_cluster(k8s_dir, resource_kind="ConfigMap", resource_api_version="v1")
        assert check_controller_resource_health_checks(cluster, k8s_dir, repo_root) == []


class TestBlueprintCompleteness:
    """Tests for authentik blueprint completeness check."""

    @pytest.fixture
    def k8s_dir(self, tmp_path: Path) -> Path:
        authentik = tmp_path / "authentik"
        authentik.mkdir()
        (authentik / "blueprints").mkdir()
        return tmp_path

    def _write_kustomization(self, k8s_dir: Path, files: list[str]) -> None:
        kust = {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "configMapGenerator": [{"name": "authentik-sso-blueprints", "files": [f"blueprints/{f}" for f in files]}],
        }
        (k8s_dir / "authentik" / "kustomization.yaml").write_text(yaml.dump(kust))

    def test_all_blueprints_listed(self, k8s_dir: Path) -> None:
        """No errors when all blueprint files are listed."""
        (k8s_dir / "authentik" / "blueprints" / "foo-sso.yaml").touch()
        (k8s_dir / "authentik" / "blueprints" / "bar-sso.yaml").touch()
        self._write_kustomization(k8s_dir, ["foo-sso.yaml", "bar-sso.yaml"])
        assert check_blueprint_completeness(k8s_dir) == []

    def test_unlisted_blueprint(self, k8s_dir: Path) -> None:
        """Reports error for blueprint file not in configMapGenerator."""
        (k8s_dir / "authentik" / "blueprints" / "foo-sso.yaml").touch()
        (k8s_dir / "authentik" / "blueprints" / "bar-sso.yaml").touch()
        self._write_kustomization(k8s_dir, ["foo-sso.yaml"])
        errors = check_blueprint_completeness(k8s_dir)
        assert len(errors) == 1
        assert "bar-sso.yaml" in errors[0]

    def test_no_authentik_dir(self, tmp_path: Path) -> None:
        """No errors when authentik directory doesn't exist."""
        assert check_blueprint_completeness(tmp_path) == []


if __name__ == "__main__":
    pytest_bazel.main()
