"""The retired GitHub Terraform bundle retained as a Flux prune gate."""

from __future__ import annotations

from cdk8s import Chart
from flux_kustomize.io.fluxcd.toolkit.kustomize import KustomizationSpecDeletionPolicy

from cluster.cdk8s.flux import Kustomization, RenderedDirectory, flux_kustomization, flux_kustomization_depends_on_many
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "github-tf"
OUTPUT_DIR = f"{GENERATED_ROOT}/{NAME}"


def github_tf(chart: Chart, directory: RenderedDirectory, tofu_controller: Kustomization) -> Kustomization:
    return flux_kustomization(
        chart,
        NAME,
        directory,
        timeout="10m",
        depends_on=flux_kustomization_depends_on_many(tofu_controller),
        deletion_policy=KustomizationSpecDeletionPolicy.ORPHAN,
    )
