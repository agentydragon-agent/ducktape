"""Retired Authentik Terraform bundle retained as the Flux prune gate."""

from __future__ import annotations

from cdk8s import Chart

from cluster.cdk8s.flux import Kustomization, RenderedDirectory, flux_kustomization, flux_kustomization_depends_on_many
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "authentik-tf"
OUTPUT_DIR = f"{GENERATED_ROOT}/authentik/tf"


def authentik_tf(chart: Chart, directory: RenderedDirectory, tofu_controller: Kustomization) -> Kustomization:
    return flux_kustomization(
        chart, NAME, directory, timeout="10m", depends_on=flux_kustomization_depends_on_many(tofu_controller)
    )
