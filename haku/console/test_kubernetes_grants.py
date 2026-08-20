"""Domain contracts for temporary Kubernetes grants."""

from __future__ import annotations

import pytest
import pytest_bazel
from pydantic import ValidationError

from haku.console.kubernetes_grant_models import KubernetesRule
from haku.console.kubernetes_grant_service import rule_covers, rules_cover


def resource_rule(**kwargs: object) -> KubernetesRule:
    return KubernetesRule(verbs=("get",), api_groups=("",), resources=("pods",), **kwargs)


def test_resource_rule_canonicalizes_values() -> None:
    rule = KubernetesRule.model_validate(
        {"api_groups": [""], "resources": ["pods"], "verbs": ["get"], "resource_names": ["pod-a"]}
    )

    assert rule.api_groups == frozenset({""})
    assert rule.resources == frozenset({"pods"})
    assert rule.resource_names == frozenset({"pod-a"})
    assert rule.model_dump(mode="json")["resource_names"] == ["pod-a"]


def test_rule_rejects_kubernetes_wire_names_inside_the_domain() -> None:
    with pytest.raises(ValidationError, match="apiGroups"):
        KubernetesRule.model_validate({"apiGroups": [""], "resources": ["pods"], "verbs": ["get"]})


def test_rule_models_rbac_collections_as_sets_and_serializes_stably() -> None:
    rule = KubernetesRule(api_groups=("apps", ""), resources=("pods", "deployments"), verbs=("list", "get"))

    assert rule.verbs == frozenset({"get", "list"})
    assert rule.model_dump(mode="json")["verbs"] == ["get", "list"]
    assert rule.model_dump(mode="json")["api_groups"] == ["", "apps"]


def test_rule_rejects_scalar_strings_for_collection_fields() -> None:
    with pytest.raises(ValidationError, match="valid frozenset"):
        KubernetesRule(api_groups=("",), resources=("pods",), verbs="get")
    with pytest.raises(ValidationError, match="valid frozenset"):
        KubernetesRule(api_groups="", resources=("pods",), verbs=("get",))


def test_rule_rejects_mixed_or_empty_shape() -> None:
    with pytest.raises(ValidationError, match="must contain resources"):
        KubernetesRule(verbs=("get",))
    with pytest.raises(ValidationError, match="must contain resources"):
        KubernetesRule(api_groups=("apps",), verbs=("get",))
    with pytest.raises(ValidationError, match="must contain resources"):
        KubernetesRule(resource_names=("pod-a",), verbs=("get",))
    with pytest.raises(ValidationError, match="at least 1 item"):
        KubernetesRule(api_groups=("",), resources=("pods",), verbs=())
    with pytest.raises(ValidationError, match="cannot mix"):
        KubernetesRule(api_groups=("",), resources=("pods",), verbs=("get",), non_resource_urls=("/healthz",))


def test_matching_is_conservative_about_resource_names() -> None:
    all_pods = resource_rule()
    one_pod = resource_rule(resource_names=("pod-a",))
    other_pod = resource_rule(resource_names=("pod-b",))

    assert rule_covers(all_pods, one_pod)
    assert not rule_covers(one_pod, other_pod)
    assert not rule_covers(one_pod, all_pods)


def test_matching_allows_only_explicit_wildcards() -> None:
    granted = KubernetesRule(api_groups=("*",), resources=("*",), verbs=("*",))
    requested = KubernetesRule(api_groups=("apps",), resources=("deployments/status",), verbs=("patch",))

    assert rule_covers(granted, requested)
    assert not rule_covers(
        KubernetesRule(api_groups=("apps",), resources=("deployments",), verbs=("patch",)), requested
    )


def test_non_resource_urls_use_exact_or_terminal_prefix_matching() -> None:
    granted = KubernetesRule(verbs=("get",), non_resource_urls=("/version", "/api/*"))

    assert rule_covers(granted, KubernetesRule(verbs=("get",), non_resource_urls=("/version", "/api/v1")))
    assert not rule_covers(granted, KubernetesRule(verbs=("get",), non_resource_urls=("/apis",)))


def test_rules_cover_requires_every_request_rule() -> None:
    granted = (resource_rule(),)
    requested = (resource_rule(), KubernetesRule(verbs=("list",), api_groups=("",), resources=("pods",)))

    assert not rules_cover(granted, requested)


if __name__ == "__main__":
    pytest_bazel.main()
