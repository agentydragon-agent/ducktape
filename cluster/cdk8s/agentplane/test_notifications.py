"""Only the staging GitHub webhook is public; workload APIs stay behind egress auth."""

from typing import Any

import pytest
import pytest_bazel
from more_itertools import one

from cluster.cdk8s.agentplane import notifications, staging
from cluster.cdk8s.agentplane.conftest import NAMESPACES


@pytest.mark.parametrize("namespace", NAMESPACES)
def test_public_notification_routes_are_webhook_only(
    namespace: str, agentplane_manifests: dict[str, list[dict[str, Any]]]
) -> None:
    rules = [
        rule
        for doc in agentplane_manifests[namespace]
        if doc["kind"] == "HTTPRoute"
        for rule in doc["spec"]["rules"]
        if any(backend["name"] == notifications.NAME for backend in rule.get("backendRefs", []))
    ]
    if namespace != staging.ENV.namespace:
        assert not rules
        return
    rule = one(rules)
    assert rule["matches"] == [{"path": {"type": "Exact", "value": "/v1/webhooks/github"}}]
    assert all(filter_["type"] == "ResponseHeaderModifier" for filter_ in rule.get("filters", []))


@pytest.mark.parametrize("namespace", NAMESPACES)
def test_only_staging_notifications_admit_gateway(
    namespace: str, agentplane_manifests: dict[str, list[dict[str, Any]]]
) -> None:
    endpoint = notifications.service(namespace)
    ingress = [
        rule
        for doc in agentplane_manifests[namespace]
        if doc["kind"] == "CiliumNetworkPolicy"
        and doc["spec"]["endpointSelector"].get("matchLabels") == endpoint.pods.selector
        for rule in doc["spec"].get("ingress", [])
        if "ingress" in rule.get("fromEntities", [])
    ]
    if namespace != staging.ENV.namespace:
        assert not ingress
        return
    assert one(ingress) == {
        "fromEntities": ["ingress"],
        "toPorts": [{"ports": [{"port": str(endpoint.pod_port), "protocol": "TCP"}]}],
    }


if __name__ == "__main__":
    pytest_bazel.main()
