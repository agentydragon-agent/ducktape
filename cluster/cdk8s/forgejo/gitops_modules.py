"""The retired tofu-controller Forgejo bundle, retained as a Flux prune gate and source owner.

Remove it only after all five legacy Terraform CRs are absent and each child Workspace
Kustomization has been rewired to an independent artifact source.
"""

from __future__ import annotations

from cdk8s import Chart

from cluster.cdk8s.flux import Kustomization, RenderedDirectory, flux_kustomization, flux_kustomization_depends_on_many
from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "forgejo-gitops"
OUTPUT_DIR = f"{GENERATED_ROOT}/forgejo/gitops"


def forgejo_gitops(chart: Chart, directory: RenderedDirectory, tofu_controller: Kustomization) -> Kustomization:
    return flux_kustomization(
        chart, NAME, directory, timeout="10m", depends_on=flux_kustomization_depends_on_many(tofu_controller)
    )
