"""CRD layering validation — HelmReleases must not mix with CRD instances."""

from __future__ import annotations

from pathlib import Path

import yaml

from cluster.validation.k8s import parse_k8s_resources
from cluster.validation.kustomize import KustomizeBuildResult

# Operator kustomizations and the CRD kinds they manage.
# Kustomizations with empty sets are part of the operator layer but don't define CRDs.
OPERATOR_CRDS: dict[str, set[str]] = {
    "external-secrets-operator": {
        "ExternalSecret",
        "ClusterExternalSecret",
        "SecretStore",
        "ClusterSecretStore",
        "Password",
        "Fake",
        "VaultDynamicSecret",
    },
    "external-secrets": set(),
    "cert-manager": {"Certificate", "CertificateRequest", "Issuer", "ClusterIssuer"},
    "cert-manager-config": set(),
    "cert-manager-trust": set(),
    "cert-manager-environment": set(),
    "cluster-ca": set(),
    "kyverno": {"ClusterPolicy", "Policy"},
    "kyverno-policies": set(),
    "vault-operator": {"Vault"},
    "vault": set(),
    "tofu-controller": {"Terraform"},
    "powerdns-operator": {"ClusterZone", "ClusterRRset"},
    "sealed-secrets": set(),
}

# Derived: CRD kind -> operator name (for error messages)
CRD_TO_OPERATOR: dict[str, str] = {
    kind: operator for operator, kinds in OPERATOR_CRDS.items() for kind in kinds
}


def check_crd_layering(result: KustomizeBuildResult) -> list[str]:
    """Check if a kustomization mixes HelmReleases with CRD instances."""
    if not result.success:
        return []

    if any(part in OPERATOR_CRDS for part in result.kustomization_path.parent.parts):
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
