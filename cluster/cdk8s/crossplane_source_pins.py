"""Apply the ConfigMap generator that supplies the canary's CI-pinned source revision."""

from __future__ import annotations

from cdk8s import Chart
from source_watcher_crds.io.fluxcd.extensions.source import ArtifactGeneratorSpecArtifacts

from cluster.cdk8s.flux import Kustomization, flux_kustomization
from cluster.cdk8s.manifest_roots import HAND_WRITTEN_ROOT

NAME = "crossplane-source-pins"
OUTPUT_DIR = f"{HAND_WRITTEN_ROOT}/{NAME}"


def source_pins(flux_chart: Chart, source_artifact: ArtifactGeneratorSpecArtifacts) -> Kustomization:
    return flux_kustomization(flux_chart, NAME, source_artifact, timeout="5m")
