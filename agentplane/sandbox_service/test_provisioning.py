"""Headless provisioning, restart recovery, and incarnation-safe administrative APIs."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
import pytest_bazel
from kubernetes_asyncio import client as k8s_client

from agentplane.sandbox_service.action_policy import ActionPolicyBindings
from agentplane.sandbox_service.api import SessionResources, create_app
from agentplane.sandbox_service.destinations import DestinationResolver, SandboxDestination
from agentplane.sandbox_service.egress import EgressInventory
from agentplane.sandbox_service.inventory import NewSandbox, ProvisioningState, SandboxInventory, SandboxView
from agentplane.sandbox_service.kubernetes_bindings import KubernetesBindings
from agentplane.sandbox_service.kubernetes_grants import RoleBindingGrant, RoleRef
from agentplane.sandbox_service.provisioning import Provisioning
from agentplane.sandbox_service.testing.fake_inventory import (
    NAMESPACE, TEMPLATE, FakeCoreV1Api, FakeCustomObjectsApi, action_policy_set, egress_policy, pod,
)
from agentplane.sandbox_service.testing.fake_rbac import FakeRbac
from agentplane.sandbox_service.testing.kubernetes import Cluster
from agentplane.subjects import ServiceAccountRef
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE, TokenVerdict
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator
from agentplane.workload_auth.principal import WorkloadPrincipalResolver
from util.kubernetes import CustomObjectsClient

TOKEN = "test-provisioner-token"
ADMIN = ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name="test-provisioner")
AUDIENCE = "test-provisioning"


class FaultyObjects(FakeCustomObjectsApi):
    fail_plural: str | None = None

    async def create_namespaced_custom_object(
        self, group: str, version: str, namespace: str, plural: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        if plural == self.fail_plural:
            raise k8s_client.ApiException(status=503)
        return await super().create_namespaced_custom_object(group, version, namespace, plural, body)


@dataclass
class Case:
    service: Provisioning
    custom: FaultyObjects
    core: FakeCoreV1Api
    rbac: FakeRbac


@pytest.fixture
def case() -> Case:
    custom, core, rbac = FaultyObjects(), FakeCoreV1Api(), FakeRbac()
    inventory = SandboxInventory(namespace=NAMESPACE, custom_objects=cast(CustomObjectsClient, custom), core_v1=cast(k8s_client.CoreV1Api, core))
    custom.objects[("egresspolicies", "test-basic")] = egress_policy("test-basic", [{"hosts": ["example.test"]}])
    custom.objects[("actionpolicysets", "test-actions")] = action_policy_set("test-actions")
    return Case(
        Provisioning(
            inventory,
            EgressInventory(namespace=NAMESPACE, custom_objects=cast(CustomObjectsClient, custom), default_policies=["test-basic"]),
            ActionPolicyBindings(namespace=NAMESPACE, custom_objects=cast(CustomObjectsClient, custom)),
            {"test-read": RoleBindingGrant(kind="RoleBinding", namespace=NAMESPACE, role_ref=RoleRef(kind="Role", name="test-reader"))},
            KubernetesBindings(inventory, cast(k8s_client.RbacAuthorizationV1Api, rbac)),
        ), custom, core, rbac,
    )


@pytest.fixture
async def api(case: Case, cluster: Cluster) -> AsyncIterator[httpx.AsyncClient]:
    cluster.fake.tokens[TOKEN] = TokenVerdict(
        username=f"system:serviceaccount:{ADMIN.namespace}:{ADMIN.name}",
        pod_name="test-provisioner-pod", pod_uid="test-provisioner-pod-uid", audiences=(AUDIENCE,),
    )
    resources = SessionResources(
        authenticate=WorkloadPrincipalAuthenticator(WorkloadPrincipalResolver(
            authentication=k8s_client.AuthenticationV1Api(cluster.api), audience=AUDIENCE,
            allowed_service_account_namespaces={SANDBOX_NAMESPACE},
        )),
        destinations=DestinationResolver(case.service.inventory, cast(k8s_client.CoreV1Api, case.core), 7000, frozenset({ADMIN})),
        manager_accounts=frozenset({ADMIN}), platform_instructions="", provisioning=case.service,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(resources)), base_url="http://test-provisioning",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        yield client


def destination(view: SandboxView) -> dict[str, object]:
    return SandboxDestination(owner=view.service_account, sandbox=view.name, sandbox_uid=view.uid).model_dump(mode="json")


async def test_headless_create_list_and_uid_pinned_lifecycle(api: httpx.AsyncClient, case: Case) -> None:
    response = await api.post("/v1/sandboxes", json={
        "slug": "test", "template": TEMPLATE, "action_policy_sets": ["test-actions"], "kubernetes_grants": ["test-read"],
        "bootstrap": "printf ready", "thread_defaults": {"model": "test-model"},
    })
    assert response.status_code == 201, response.text
    view = SandboxView.model_validate(response.json())
    assert view.binding is not None and view.binding.bootstrap == "printf ready"
    assert view.kubernetes_grants_ready
    assert len(case.rbac.bindings) == 1
    assert await case.service.inventory.pending_grants(view.name) is None
    assert len((await api.get("/v1/sandboxes")).json()) == 1
    assert (await api.get("/v1/sandbox-templates")).json() == [TEMPLATE]
    request = {"destination": destination(view)}
    assert (await api.post("/v1/sandboxes/delete", json=request)).status_code == 409
    stale = {"destination": {**destination(view), "sandbox_uid": str(uuid4())}}
    for operation in ("suspend", "resume", "delete"):
        assert (await api.post(f"/v1/sandboxes/{operation}", json=stale)).status_code == 404
    assert (await api.post("/v1/sandboxes/suspend", json=request)).status_code == 204
    assert (await api.post("/v1/sandboxes/resume", json=request)).status_code == 204
    assert (await api.post("/v1/sandboxes/suspend", json=request)).status_code == 204
    assert (await api.post("/v1/sandboxes/delete", json=request)).status_code == 204


async def test_partial_create_recovers_from_kubernetes_state_without_app(case: Case) -> None:
    case.custom.fail_plural = "actionpolicybindings"
    with pytest.raises(k8s_client.ApiException):
        await case.service.create(NewSandbox(slug="test", template=TEMPLATE, action_policy_sets=["test-actions"], kubernetes_grants=["test-read"]))
    (view,) = await case.service.inventory.list_sandboxes()
    case.core.pods[view.name] = pod(view.name, phase="Running", ready=True, ip="10.0.0.1")
    assert (await case.service.inventory.get(view.name)).state == ProvisioningState.WAITING_FOR_GRANTS
    assert await case.service.inventory.pending_grants(view.name) is not None
    case.custom.fail_plural = None
    # A fresh service with a changed catalog must use the recorded concrete grant, not current UI defaults.
    restarted = replace(case.service, grants={})
    await restarted.reconcile_once()
    await restarted.reconcile_once()
    assert await restarted.inventory.pending_grants(view.name) is None
    assert (await restarted.inventory.get(view.name)).state == ProvisioningState.RUNNING
    assert len([key for key in case.custom.objects if key[0] == "egressbindings"]) == 1
    assert len([key for key in case.custom.objects if key[0] == "actionpolicybindings"]) == 1
    assert len(case.rbac.bindings) == 1
    assert next(iter(case.rbac.bindings.values())).role_ref.name == "test-reader"


async def test_foreign_binding_is_not_overwritten_and_provisioning_stays_pending(case: Case) -> None:
    case.custom.fail_plural = "actionpolicybindings"
    with pytest.raises(k8s_client.ApiException):
        await case.service.create(NewSandbox(slug="test", template=TEMPLATE, action_policy_sets=["test-actions"]))
    (view,) = await case.service.inventory.list_sandboxes()
    binding = next(value for (kind, _), value in case.custom.objects.items() if kind == "egressbindings")
    binding["spec"]["policies"] = ["test-foreign"]
    case.custom.fail_plural = None
    await case.service.reconcile_once()
    assert binding["spec"]["policies"] == ["test-foreign"]
    assert await case.service.inventory.pending_grants(view.name) is not None


async def test_authorization_precedes_creation(api: httpx.AsyncClient, cluster: Cluster, case: Case) -> None:
    cluster.fake.tokens[TOKEN] = TokenVerdict(
        username=f"system:serviceaccount:{ADMIN.namespace}:test-untrusted", pod_name="test-untrusted-pod",
        pod_uid="test-untrusted-pod-uid", audiences=(AUDIENCE,),
    )
    response = await api.post("/v1/sandboxes", json={"slug": "test", "template": TEMPLATE})
    assert response.status_code == 403
    assert not case.core.service_accounts
    assert not await case.service.inventory.list_sandboxes()


if __name__ == "__main__":
    pytest_bazel.main()
