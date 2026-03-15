"""CRD layering validation — HelmReleases must not mix with CRD instances."""

from __future__ import annotations

from pathlib import Path

import yaml

from cluster.validation.k8s import parse_k8s_resources
from cluster.validation.kustomize import KustomizeBuildResult

# Map CRD kinds to their operator Kustomization names
CRD_TO_OPERATOR: dict[str, str] = {
    # external-secrets-operator
    "ExternalSecret": "external-secrets-operator",
    "ClusterExternalSecret": "external-secrets-operator",
    "SecretStore": "external-secrets-operator",
    "ClusterSecretStore": "external-secrets-operator",
    "Password": "external-secrets-operator",
    "Fake": "external-secrets-operator",
    "VaultDynamicSecret": "external-secrets-operator",
    # cert-manager
    "Certificate": "cert-manager",
    "CertificateRequest": "cert-manager",
    "Issuer": "cert-manager",
    "ClusterIssuer": "cert-manager",
    # kyverno
    "ClusterPolicy": "kyverno",
    "Policy": "kyverno",
    # vault-operator
    "Vault": "vault-operator",
    # tofu-controller
    "Terraform": "tofu-controller",
    # powerdns-operator
    "ClusterZone": "powerdns-operator",
    "ClusterRRset": "powerdns-operator",
}

# Kustomizations that ARE operators (or part of the operator layer) don't need to
# depend on themselves. Derived from CRD_TO_OPERATOR values plus related config kustomizations.
OPERATOR_KUSTOMIZATIONS = set(CRD_TO_OPERATOR.values()) | {
    "external-secrets",  # config kustomization
    "cert-manager-config",
    "cert-manager-trust",
    "cert-manager-environment",
    "kyverno-policies",
    "vault",
    "tofu-controller",
    "sealed-secrets",
    "cluster-ca",  # Uses cert-manager CRDs but is part of cert-manager layer
}


def check_crd_layering(result: KustomizeBuildResult) -> list[str]:
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


def make_build_result(path: Path, yaml_output: str) -> KustomizeBuildResult:
    return KustomizeBuildResult(
        kustomization_path=path, success=True, resources=parse_k8s_resources(yaml.safe_load_all(yaml_output))
    )
