"""Validate namespace-local Flux post-build substitution sources."""

from __future__ import annotations

from collections.abc import Iterable

from cluster.validation.cluster import ParsedCluster
from cluster.validation.k8s import K8sResource

_REFLECTION_ALLOWED = "reflector.v1.k8s.emberstack.com/reflection-allowed"
_REFLECTION_ALLOWED_NAMESPACES = "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces"
_REFLECTION_AUTO_ENABLED = "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"
_REFLECTION_AUTO_NAMESPACES = "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"


def _resources(cluster: ParsedCluster) -> Iterable[K8sResource]:
    for resources in cluster.source_resources.values():
        yield from resources
    for result in cluster.build_results:
        yield from result.resources


def _targets_namespace(value: str | None, namespace: str) -> bool:
    if not value:
        return False
    return "*" in value or namespace in {item.strip() for item in value.split(",")}


def _is_auto_reflected_to(resource: K8sResource, namespace: str) -> bool:
    annotations = resource.metadata.annotations
    return (
        annotations.get(_REFLECTION_ALLOWED) == "true"
        and _targets_namespace(annotations.get(_REFLECTION_ALLOWED_NAMESPACES), namespace)
        and annotations.get(_REFLECTION_AUTO_ENABLED) == "true"
        and _targets_namespace(annotations.get(_REFLECTION_AUTO_NAMESPACES), namespace)
    )


def check_postbuild_substitution_sources(cluster: ParsedCluster) -> list[str]:
    """Return missing namespace-local postBuild substitution sources.

    Flux reads ``postBuild.substituteFrom`` ConfigMaps and Secrets only from the
    Kustomization CR's namespace. A source in another namespace is acceptable
    only when Emberstack reflector is configured to auto-reflect it there.
    Optional references are deliberately skipped: Flux permits them to be absent.
    """
    resources = list(_resources(cluster))
    errors: list[str] = []

    for consumer, spec in cluster.active_flux_kustomizations.items():
        if not spec.namespace or spec.post_build is None:
            continue
        for source in spec.post_build.substitute_from:
            if source.optional or not source.name:
                continue
            matching = [resource for resource in resources if resource.kind == source.kind and resource.name == source.name]
            if any(resource.namespace == spec.namespace for resource in matching):
                continue
            if any(_is_auto_reflected_to(resource, spec.namespace) for resource in matching):
                continue
            errors.append(
                f"{consumer} (ns={spec.namespace}) postBuild substituteFrom "
                f"'{source.kind}/{source.name}' is unavailable in its namespace. "
                "Flux substitution sources are namespace-local; create it there or configure "
                "an Emberstack reflector auto-copy."
            )

    return errors
