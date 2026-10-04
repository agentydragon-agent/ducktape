"""The per-key model allowlists tf/gitops/litellm-keys/main.tf scopes its LiteLLM virtual
keys to, derived from model_rosters.py and handed to the module as the `model_allowlists`
variable of its generated Terraform CR (generate_manifests.py). Every name is checked
against what the main proxy serves before it is written.
"""

from __future__ import annotations

from cdk8s import App, Chart
from pydantic import BaseModel, ConfigDict

from cluster.cdk8s import terraform
from cluster.cdk8s.flux import Kustomization, RenderedDirectory, flux_kustomization, flux_kustomization_depends_on_many
from cluster.cdk8s.manifest_roots import HAND_WRITTEN_ROOT
from cluster.cdk8s.model_rosters import SERVED_ROUTES
from cluster.cdk8s.model_selections import KEY_FALLBACK_ROUTES, KEY_MODEL_ROUTES
from cluster.cdk8s.secret_ref import SecretRef

OUTPUT_DIR = f"{HAND_WRITTEN_ROOT}/litellm/keys-tf"


def model_allowlists() -> dict[str, list[str]]:
    """Serialize key policy at the Terraform boundary, without rebuilding model IDs."""
    for lane, routes in KEY_MODEL_ROUTES.items():
        if unserved := [route.id for route in routes if route not in SERVED_ROUTES]:
            raise ValueError(f"{lane=} selects unserved routes: {unserved}")
    return {lane: [route.id for route in routes] for lane, routes in KEY_MODEL_ROUTES.items()}


def model_fallbacks() -> dict[str, list[str]]:
    for lane, routes in KEY_FALLBACK_ROUTES.items():
        if any(route not in KEY_MODEL_ROUTES[lane] for route in routes):
            raise ValueError(f"{lane=} selects fallback routes outside its allowlist")
    return {lane: [route.id for route in routes] for lane, routes in KEY_FALLBACK_ROUTES.items()}


class KeysVars(BaseModel):
    """The inputs of tf/gitops/litellm-keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_allowlists: dict[str, list[str]]
    model_fallbacks: dict[str, list[str]]


def keys_chart(app: App) -> Chart:
    """Mints the agent and laptop-client LiteLLM virtual keys (tf/gitops/litellm-keys).
    Needs the SOPS-managed master key and a serving LiteLLM with its virtual-key DB;
    tofu-controller retries on its interval until LiteLLM is up.
    """
    chart = Chart(app, "litellm-keys", disable_resource_name_hashes=True)
    terraform.gitops_terraform(
        chart,
        "terraform",
        name="litellm-keys",
        variables=KeysVars(model_allowlists=model_allowlists(), model_fallbacks=model_fallbacks()),
        env=[
            # The narrow SOPS age private key (litellm-clients-sops-age-key.sops.yaml
            # beside this CR) that decrypts the module's pinned client-key files for
            # its `sops_file` data sources -- single-purpose, not the broad cluster key.
            terraform.secret_env(
                "SOPS_AGE_KEY", SecretRef(namespace=terraform.NAMESPACE, name="litellm-clients-sops-age-key").key("key")
            )
        ],
    )
    return chart


# The litellm-keys Terraform CR lives DOWNSTREAM of the litellm app, not in
# litellm-secrets: minting virtual keys needs a serving LiteLLM with its
# virtual-key DB. Coupling the TF's health into litellm-secrets (the app's
# dependency) deadlocked the 2026-07-02 rollout — the app never applied the
# DATABASE_URL deployment because its secrets layer waited on a TF apply that
# needed the app. Dependency direction here is the fix.
def litellm_keys_tf(chart: Chart, directory: RenderedDirectory, tofu_controller: Kustomization) -> Kustomization:
    name = "litellm-keys-tf"
    return flux_kustomization(
        chart, name, directory, timeout="10m", depends_on=flux_kustomization_depends_on_many(tofu_controller)
    )
