"""The inventory's reading of the Sandbox and Pod, and the objects each operation writes."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_bazel
from google.protobuf.json_format import MessageToDict
from kubernetes_asyncio import client as k8s_client

from agentplane.action_service.policies.resources import CALLER_LABEL
from agentplane.sandbox_service.inventory import INITIALIZING, SandboxInventory
from agentplane.sandbox_service.kubernetes_views import MANAGED_LABEL
from agentplane.sandbox_service.models import SandboxConflictError, SandboxNotFoundError
from agentplane.sandbox_service.protocol_pb2 import CreateSandboxRequest
from agentplane.sandbox_service.testing.fake_inventory import (
    NAMESPACE,
    POD_TEMPLATE,
    VOLUME_CLAIM_TEMPLATES,
    FakeCoreV1Api,
    FakeCustomObjectsApi,
    pod,
    sandbox,
)
from util.agent_sandbox import OperatingMode

_READY = {"conditions": [{"type": "Ready", "status": "True", "reason": "PodReady"}], "nodeName": "test-node"}


def _populate_one_of_each_state(custom_objects: FakeCustomObjectsApi, core_v1: FakeCoreV1Api) -> None:
    custom_objects.objects[("sandboxes", "podless")] = sandbox("podless")
    custom_objects.objects[("sandboxes", "starting")] = sandbox("starting")
    core_v1.pods["starting"] = pod("starting", phase="Pending", ready=False, ip=None, waiting_reason="ImagePullBackOff")
    custom_objects.objects[("sandboxes", "live")] = sandbox("live", status=_READY)
    core_v1.pods["live"] = pod("live", phase="Running", ready=True, ip="10.0.0.7")
    custom_objects.objects[("sandboxes", "paused")] = sandbox("paused", operating_mode="Suspended")
    # Not Agentplane's: another tenant's Sandbox in the same namespace stays invisible.
    custom_objects.objects[("sandboxes", "foreign")] = {
        "metadata": {
            "name": "foreign",
            "namespace": NAMESPACE,
            "uid": str(uuid4()),
            "creationTimestamp": "2026-09-01T12:00:00Z",
        },
        "spec": {"podTemplate": POD_TEMPLATE},
    }


async def test_list_keeps_each_resource_status_separate(
    inventory: SandboxInventory, custom_objects: FakeCustomObjectsApi, core_v1: FakeCoreV1Api
) -> None:
    _populate_one_of_each_state(custom_objects, core_v1)

    views = {view.name: view for view in await inventory.list_sandboxes()}

    assert {name: (view.operating_mode, view.HasField("pod")) for name, view in views.items()} == {
        "podless": (OperatingMode.RUNNING, False),
        "starting": (OperatingMode.RUNNING, True),
        "live": (OperatingMode.RUNNING, True),
        "paused": (OperatingMode.SUSPENDED, False),
    }
    live = views["live"]
    assert live.HasField("pod")
    assert live.pod.node_name == "test-node"
    assert MessageToDict(live.status) == {
        "conditions": [{"type": "Ready", "status": "True", "reason": "PodReady"}],
        "nodeName": "test-node",
    }
    pod_status = MessageToDict(live.pod.status)
    assert (pod_status["phase"], pod_status["podIP"]) == ("Running", "10.0.0.7")
    assert pod_status["conditions"] == [{"type": "Ready", "status": "True"}]
    assert pod_status["containerStatuses"][0]["state"] == {"running": {}}
    # A Pod held up by its image is visible as such, so the app can say why nothing is running.
    starting = views["starting"].pod
    assert starting is not None
    starting_status = MessageToDict(starting.status)
    assert starting_status["containerStatuses"][0]["state"] == {
        "waiting": {"reason": "ImagePullBackOff", "message": "ImagePullBackOff on starting"}
    }
    assert not views["podless"].HasField("pod")
    assert not views["podless"].HasField("status")


async def test_get_reads_one_sandbox_and_refuses_foreign_or_missing_ones(
    inventory: SandboxInventory, custom_objects: FakeCustomObjectsApi, core_v1: FakeCoreV1Api
) -> None:
    _populate_one_of_each_state(custom_objects, core_v1)

    view = await inventory.get("live")

    assert view.HasField("pod")
    assert view.operating_mode == OperatingMode.RUNNING
    assert MessageToDict(view.pod.status)["podIP"] == "10.0.0.7"
    with pytest.raises(SandboxNotFoundError):
        await inventory.get("foreign")
    with pytest.raises(SandboxNotFoundError):
        await inventory.get("never-made")


async def test_create_stamps_a_labelled_sandbox_from_the_template(
    inventory: SandboxInventory, custom_objects: FakeCustomObjectsApi
) -> None:
    view = await inventory.create(CreateSandboxRequest(name="my-task", template="agentplane-test-runner"))

    assert view.name == "my-task"
    assert view.operating_mode == OperatingMode.SUSPENDED
    assert not view.HasField("pod")
    stored = custom_objects.objects[("sandboxes", view.name)]
    assert stored["kind"] == "Sandbox"
    assert stored["metadata"]["labels"] == {MANAGED_LABEL: "true"}
    assert stored["metadata"]["annotations"][INITIALIZING] == "true"
    assert stored["spec"]["volumeClaimTemplates"] == VOLUME_CLAIM_TEMPLATES
    assert stored["spec"]["shutdownPolicy"] == "Retain"
    # Every other field of the Pod is the template's; only what it runs as is this sandbox's.
    assert stored["spec"]["podTemplate"] == {
        **POD_TEMPLATE,
        "spec": {**POD_TEMPLATE.get("spec", {}), "serviceAccountName": view.name},
    }


async def test_create_gives_the_sandbox_a_service_account_of_its_own_that_it_runs_as(
    inventory: SandboxInventory, custom_objects: FakeCustomObjectsApi, core_v1: FakeCoreV1Api
) -> None:
    """What the Pod runs as is what egress and the Action Service authenticate it by, so a sandbox
    sharing the template's account could only ever be granted what every other sandbox is. The
    caller label is what the Action Service admits it on; without it the sandbox authenticates and
    reaches no route."""
    view = await inventory.create(CreateSandboxRequest(name="my-task", template="agentplane-test-runner"))

    assert core_v1.service_accounts == {}  # The CR precedes its account.
    await inventory.ensure_service_account(view)
    account = core_v1.service_accounts[view.name]
    assert account.metadata.labels == {MANAGED_LABEL: "true", CALLER_LABEL: "true"}
    assert (
        custom_objects.objects[("sandboxes", view.name)]["spec"]["podTemplate"]["spec"]["serviceAccountName"]
        == view.name
    )
    # Owned by the Sandbox, so deleting the sandbox takes the identity with it.
    (owner,) = account.metadata.owner_references
    assert (owner.kind, owner.name, owner.uid) == (
        "Sandbox",
        view.name,
        custom_objects.objects[("sandboxes", view.name)]["metadata"]["uid"],
    )


async def test_create_leaves_no_service_account_behind_when_the_sandbox_is_refused(
    inventory: SandboxInventory, custom_objects: FakeCustomObjectsApi, core_v1: FakeCoreV1Api
) -> None:
    """A refused CR never leaves a dangling account."""
    custom_objects.create_fails = True

    with pytest.raises(k8s_client.ApiException):
        await inventory.create(CreateSandboxRequest(name="my-task", template="agentplane-test-runner"))

    assert core_v1.service_accounts == {}


async def test_create_retries_the_same_name(inventory: SandboxInventory) -> None:
    spec = CreateSandboxRequest(name="twice", template="agentplane-test-runner")

    first, second = await inventory.create(spec), await inventory.create(spec)

    assert first.name == second.name == "twice"
    assert first.uid == second.uid


async def test_suspend_and_resume_patch_the_operating_mode(
    inventory: SandboxInventory, custom_objects: FakeCustomObjectsApi, core_v1: FakeCoreV1Api
) -> None:
    _populate_one_of_each_state(custom_objects, core_v1)

    await inventory.suspend("live")
    suspended = await inventory.get("live")
    await inventory.resume("live")
    resumed = await inventory.get("live")

    assert custom_objects.patches == [
        ("sandboxes", "live", {"metadata": {"uid": str(suspended.uid)}, "spec": {"operatingMode": "Suspended"}}),
        ("sandboxes", "live", {"metadata": {"uid": str(resumed.uid)}, "spec": {"operatingMode": "Running"}}),
    ]
    assert (suspended.operating_mode, resumed.operating_mode) == (OperatingMode.SUSPENDED, OperatingMode.RUNNING)
    with pytest.raises(SandboxNotFoundError):
        await inventory.suspend("foreign")


async def test_create_intent_conflicts_and_caller_cannot_adopt_name(inventory: SandboxInventory) -> None:
    spec = CreateSandboxRequest(name="same", template="agentplane-test-runner")
    first = await inventory.create(spec, caller="a")
    retry = await inventory.retry(spec, caller="a")
    assert retry is not None
    assert retry.uid == first.uid
    with pytest.raises(SandboxConflictError):
        await inventory.create(spec, caller="b")
    with pytest.raises(SandboxConflictError):
        await inventory.create(CreateSandboxRequest(name="same", template="other"), caller="a")


async def test_retry_recovers_lost_cr_reply(inventory: SandboxInventory, custom_objects: FakeCustomObjectsApi) -> None:
    original = custom_objects.create_namespaced_custom_object

    async def committed_then_lost(*args: object) -> dict[str, object]:
        await original(*args)
        raise k8s_client.ApiException(status=503)

    custom_objects.create_namespaced_custom_object = committed_then_lost  # type: ignore[method-assign]
    spec = CreateSandboxRequest(name="recover", template="agentplane-test-runner")
    view = await inventory.create(spec)
    retry = await inventory.retry(spec)
    assert retry is not None
    assert retry.uid == view.uid
    assert len([key for key in custom_objects.objects if key[0] == "sandboxes"]) == 1


async def test_service_account_conflicts_with_stale_uid(inventory: SandboxInventory, core_v1: FakeCoreV1Api) -> None:
    view = await inventory.create(CreateSandboxRequest(name="same", template="agentplane-test-runner"))
    await inventory.ensure_service_account(view)
    await inventory.ensure_service_account(view)
    core_v1.service_accounts["same"].metadata.owner_references[0].uid = str(uuid4())
    with pytest.raises(SandboxConflictError):
        await inventory.ensure_service_account(view)


if __name__ == "__main__":
    pytest_bazel.main()

# gazelle:include_dep @pypi//protobuf
