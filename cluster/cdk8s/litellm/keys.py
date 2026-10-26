"""Completed LiteLLM handoff retained as a Flux prune gate during Terraform finalization."""

from __future__ import annotations

from cdk8s import Chart

from cluster.cdk8s.flux import Kustomization, RenderedDirectory, flux_kustomization, flux_kustomization_depends_on_many
from cluster.cdk8s.manifest_roots import HAND_WRITTEN_ROOT

OUTPUT_DIR = f"{HAND_WRITTEN_ROOT}/litellm/keys-tf"
TF_MODULE = "litellm-keys"


def litellm_keys_tf(
    chart: Chart, directory: RenderedDirectory, tofu_controller: Kustomization, litellm: Kustomization
) -> Kustomization:
    """Keep an empty inventory owner so Flux prunes the completed Terraform CR."""
    return flux_kustomization(
        chart,
        "litellm-keys-tf",
        directory,
        timeout="20m",
        depends_on=flux_kustomization_depends_on_many(tofu_controller, litellm),
        description="Prune the completed LiteLLM Terraform handoff; retain its credential sibling and source until finalization.",
    )
