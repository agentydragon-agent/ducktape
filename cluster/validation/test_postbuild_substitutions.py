"""Tests for namespace-local Flux post-build substitution validation."""

from __future__ import annotations

from pathlib import Path

from cluster.validation.cluster import ParsedCluster
from cluster.validation.flux import FluxKustomizationSpec, PostBuild, SubstituteFrom
from cluster.validation.k8s import parse_k8s_resources
from cluster.validation.postbuild_substitutions import check_postbuild_substitution_sources


def _consumer(namespace: str = "ducktape-flux", *, optional: bool = False) -> ParsedCluster:
    return ParsedCluster(
        flux_kustomizations={
            "consumer": FluxKustomizationSpec(
                namespace=namespace,
                post_build=PostBuild(substitute_from=[SubstituteFrom(kind="ConfigMap", name="settings", optional=optional)]),
            )
        }
    )


def _config_map(namespace: str, annotations: dict[str, str] | None = None):
    return parse_k8s_resources(
        [
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "settings", "namespace": namespace, "annotations": annotations or {}},
            }
        ]
    )[0]


def test_rejects_a_substitution_source_in_another_namespace() -> None:
    cluster = _consumer()
    cluster.source_resources = {Path("settings.yaml"): [_config_map("flux-system")]}

    assert check_postbuild_substitution_sources(cluster) == [
        "consumer (ns=ducktape-flux) postBuild substituteFrom 'ConfigMap/settings' is unavailable in its namespace. "
        "Flux substitution sources are namespace-local; create it there or configure an Emberstack reflector auto-copy."
    ]


def test_accepts_a_namespace_local_substitution_source() -> None:
    cluster = _consumer()
    cluster.source_resources = {Path("settings.yaml"): [_config_map("ducktape-flux")]}

    assert check_postbuild_substitution_sources(cluster) == []


def test_accepts_an_explicit_reflector_auto_copy() -> None:
    cluster = _consumer()
    cluster.source_resources = {
        Path("settings.yaml"): [
            _config_map(
                "flux-system",
                {
                    "reflector.v1.k8s.emberstack.com/reflection-allowed": "true",
                    "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces": "ducktape-flux",
                    "reflector.v1.k8s.emberstack.com/reflection-auto-enabled": "true",
                    "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces": "ducktape-flux",
                },
            )
        ]
    }

    assert check_postbuild_substitution_sources(cluster) == []


def test_allows_an_optional_missing_source() -> None:
    assert check_postbuild_substitution_sources(_consumer(optional=True)) == []
