"""Move the Forgejo SSH-key root from tofu-controller to Crossplane OpenTofu."""

from __future__ import annotations

from cdk8s import App, Chart

from cluster.cdk8s import opentofu, terraform
from cluster.cdk8s.flux import Kustomization, RenderedDirectory, flux_kustomization, flux_kustomization_depends_on_many
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "crossplane-forgejo-agentydragon"
OUTPUT_DIR = f"{GENERATED_ROOT}/{NAME}"
TF_MODULE_NAME = "forgejo-agentydragon"
PROVIDER_CONFIG_NAME = NAME
WORKSPACE_NAME = TF_MODULE_NAME
STATE_SCHEMA = terraform.gitops_state_schema(TF_MODULE_NAME)


def chart(app: App) -> Chart:
    chart = Chart(app, NAME, disable_resource_name_hashes=True)
    opentofu.gitops_workspace(
        chart,
        "workspace",
        name=WORKSPACE_NAME,
        provider_config_name=PROVIDER_CONFIG_NAME,
        schema=STATE_SCHEMA,
        directory=f"tf/gitops/{TF_MODULE_NAME}",
        management_policies=["Observe", "Create", "Update"],
    )
    return chart


def resources(
    flux_chart: Chart,
    directory: RenderedDirectory,
    opentofu_provider: Kustomization,
    tofu_state_db: Kustomization,
    forgejo_gitops: Kustomization,
) -> Kustomization:
    """Start Crossplane only after tofu-controller has pruned the old Terraform root."""
    return flux_kustomization(
        flux_chart,
        NAME,
        directory,
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(opentofu_provider, tofu_state_db, forgejo_gitops),
        description=(
            "Take over forgejo-agentydragon from tofu-controller using its existing PostgreSQL state; "
            "the dependency on forgejo-gitops serializes the controller handoff."
        ),
    )
