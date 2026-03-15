"""Non-graph validation checks for cluster configuration."""

from __future__ import annotations

from pathlib import Path

from cluster.scripts.validate_cluster.cluster import ParsedCluster
from cluster.scripts.validate_cluster.flux import FluxKustomization
from cluster.scripts.validate_cluster.k8s import K8sResource
from cluster.scripts.validate_cluster.kustomize import KustomizeBuildResult, KustomizeFile

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

# These Kustomizations ARE the operators, so they don't need to depend on themselves
OPERATOR_KUSTOMIZATIONS = {
    "external-secrets-operator",
    "external-secrets",  # config kustomization
    "cert-manager",
    "cert-manager-config",
    "cert-manager-trust",
    "cert-manager-environment",
    "kyverno",
    "kyverno-policies",
    "vault-operator",
    "vault",
    "tofu-controller",
    "sealed-secrets",
    "powerdns-operator",
    "cluster-ca",  # Uses cert-manager CRDs but is part of cert-manager layer
}

# Resource kinds that have async reconciliation and need healthChecks
# to surface their status through the parent Kustomization.
_HEALTH_CHECK_REQUIRED_KINDS = ["HelmRelease", "Terraform"]


def check_crd_layering(result: KustomizeBuildResult) -> list[str]:
    """Check if a kustomization mixes HelmReleases with CRD instances."""
    if not result.success:
        return []

    kust_name = result.kustomization_path.parent.name

    # Skip operator kustomizations
    if any(part in OPERATOR_KUSTOMIZATIONS for part in result.kustomization_path.parent.parts):
        return []

    # Skip overlay directories
    if "overlays" in result.kustomization_path.parts:
        return []

    has_helmrelease = False
    crd_instances: list[tuple[str, str]] = []

    for resource in result.resources:
        if resource.kind == "HelmRelease":
            has_helmrelease = True
        if resource.kind in CRD_TO_OPERATOR:
            crd_instances.append((resource.kind, CRD_TO_OPERATOR[resource.kind]))

    if has_helmrelease and crd_instances:
        unique_crds = sorted({f"{k} (needs {op})" for k, op in crd_instances})
        return [
            f"CRD layering violation: Mixes HelmRelease with CRD instances: {', '.join(unique_crds)}. "
            f"Split CRD instances into a separate '{kust_name}-secrets/' Kustomization. "
            f"See AGENTS.md 'Flux Kustomization Layering'."
        ]

    return []


def _kust_deploys_kind(kind: str, kust: KustomizeFile, source_resources: dict[Path, list[K8sResource]]) -> bool:
    """Check if a kustomization references any resources of the given kind."""
    return any(
        resource.kind == kind
        for resource_path in kust.resources
        for resource in source_resources.get(resource_path, [])
    )


def _resolve_flux_kust_dir(flux_kust: FluxKustomization, repo_root: Path) -> Path | None:
    """Resolve flux kustomization spec_path to an absolute directory path."""
    if not flux_kust.spec_path:
        return None
    return (repo_root / flux_kust.spec_path.removeprefix("./")).resolve()


def check_controller_resource_health_checks(cluster: ParsedCluster, k8s_dir: Path, repo_root: Path) -> list[str]:
    """Check that flux kustomizations deploying controller-reconciled resources have healthChecks."""
    return [
        f"{name}: deploys a {kind} but has no healthChecks for it. "
        f"Add healthChecks with kind: {kind} to {flux_kust.file_path.relative_to(k8s_dir)}."
        for name, flux_kust in cluster.flux_kustomizations.items()
        if (kust_dir := _resolve_flux_kust_dir(flux_kust, repo_root))
        if (kust := cluster.kustomize_files.get(kust_dir / "kustomization.yaml"))
        for kind in _HEALTH_CHECK_REQUIRED_KINDS
        if _kust_deploys_kind(kind, kust, cluster.source_resources)
        if not any(hc.kind == kind for hc in flux_kust.health_checks)
    ]
