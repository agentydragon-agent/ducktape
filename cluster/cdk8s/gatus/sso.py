"""Inline Crossplane ownership of tf/gitops/gatus-sso, preserving its existing state."""

from cdk8s import App, Chart

from cluster.cdk8s import opentofu, terraform
from cluster.cdk8s.flux import (
    Kustomization,
    RenderedDirectory,
    artifact_directory,
    flux_kustomization,
    flux_kustomization_depends_on_many,
)
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "crossplane-gatus-sso"
TF_MODULE_NAME = "gatus-sso"
OUTPUT_DIR = f"{GENERATED_ROOT}/authentik/tf/{NAME}"
KUBERNETES_IDENTITY = "opentofu-gatus-sso"


def chart(app: App) -> Chart:
    chart = Chart(app, NAME, disable_resource_name_hashes=True)
    identity = opentofu.kubernetes_service_account(chart, KUBERNETES_IDENTITY)
    opentofu.secret_access(
        chart, "authentik-secrets", identity=identity, namespace="authentik", read=["authentik-bootstrap"], write=[]
    )
    opentofu.secret_access(
        chart, "gatus-secrets", identity=identity, namespace="gatus", read=[], write=["gatus-oidc-secret"]
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
    opentofu_provider: Kustomization,
    tofu_state_db: Kustomization,
    previous_owner: Kustomization,
) -> Kustomization:
    """Wait for the previous bundle to finish pruning the old Terraform CR."""
    return flux_kustomization(
        chart,
        NAME,
        previous_owner.spec.source_ref,
        path=f"./{artifact_directory(directory.artifact)}",
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(opentofu_provider, tofu_state_db, previous_owner),
    )
