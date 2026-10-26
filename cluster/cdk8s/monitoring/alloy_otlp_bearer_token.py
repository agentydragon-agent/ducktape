"""Inline Crossplane ownership of tf/gitops/alloy-otlp-bearer-token, preserving its existing state."""

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

NAME = "crossplane-alloy-otlp-bearer-token"
TF_MODULE_NAME = "alloy-otlp-bearer-token"
OUTPUT_DIR = f"{GENERATED_ROOT}/authentik/tf/{NAME}"
KUBERNETES_IDENTITY = "opentofu-alloy-otlp-bearer-token"


def chart(app: App) -> Chart:
    chart = Chart(app, NAME, disable_resource_name_hashes=True)
    identity = opentofu.kubernetes_service_account(chart, KUBERNETES_IDENTITY)
    opentofu.secret_access(
        chart, "authentik-secrets", identity=identity, namespace="authentik", read=["authentik-bootstrap"], write=[]
    )
    opentofu.secret_access(
        chart,
        "agents-infra-secrets",
        identity=identity,
        namespace="agents-infra",
        read=[],
        write=["alloy-otlp-client-credentials"],
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
) -> Kustomization:
    """Apply the Workspace after its provider and state backend are ready."""
    return flux_kustomization(
        chart,
        NAME,
        KustomizationSpecSourceRef(
            kind=KustomizationSpecSourceRefKind.EXTERNAL_ARTIFACT, name=source.name, namespace=flux.NAMESPACE
        ),
        path=f"./{artifact_directory(directory.artifact)}",
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(opentofu_provider, tofu_state_db),
        health_check_exprs=[opentofu.WORKSPACE_HEALTH_CHECK_EXPR],
    )
