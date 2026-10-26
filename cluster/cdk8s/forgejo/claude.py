"""Inline Crossplane ownership of tf/gitops/forgejo-claude, preserving its existing state."""

from cdk8s import App, Chart
from flux_kustomize.io.fluxcd.toolkit.kustomize import KustomizationSpecSourceRef, KustomizationSpecSourceRefKind
from source_watcher_crds.io.fluxcd.extensions.source import ArtifactGeneratorSpecArtifacts

from cluster.cdk8s import flux, opentofu, terraform
from cluster.cdk8s.flux import (
    Kustomization,
    RenderedDirectory,
    artifact_directory,
    flux_kustomization,
    flux_kustomization_depends_on_many,
)
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "crossplane-forgejo-claude"
TF_MODULE_NAME = "forgejo-claude"
OUTPUT_DIR = f"{GENERATED_ROOT}/forgejo/gitops/{NAME}"
KUBERNETES_IDENTITY = "opentofu-forgejo-claude"


def chart(app: App) -> Chart:
    chart = Chart(app, NAME, disable_resource_name_hashes=True)
    identity = opentofu.kubernetes_service_account(chart, KUBERNETES_IDENTITY)
    opentofu.secret_access(
        chart,
        "forgejo-secrets",
        identity=identity,
        namespace="forgejo",
        read=["forgejo-admin-password"],
        write=["claude-forgejo-credentials", "forgejo-token-mint-claude"],
    )
    opentofu.gitops_workspace(
        chart,
        "workspace",
        name=TF_MODULE_NAME,
        provider_config_name=NAME,
        schema=terraform.gitops_state_schema(TF_MODULE_NAME),
        directory=f"tf/gitops/{TF_MODULE_NAME}",
        management_policies=["Observe", "Create", "Update"],
        kubernetes_identity=KUBERNETES_IDENTITY,
    )
    return chart


def resources(
    chart: Chart,
    directory: RenderedDirectory,
    source: ArtifactGeneratorSpecArtifacts,
    opentofu_provider: Kustomization,
    tofu_state_db: Kustomization,
    previous_owner: Kustomization,
) -> Kustomization:
    """Wait for the previous bundle to finish pruning the old Terraform CR."""
    return flux_kustomization(
        chart,
        NAME,
        KustomizationSpecSourceRef(
            kind=KustomizationSpecSourceRefKind.EXTERNAL_ARTIFACT, name=source.name, namespace=flux.NAMESPACE
        ),
        path=f"./{artifact_directory(directory.artifact)}",
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(opentofu_provider, tofu_state_db, previous_owner),
    )
