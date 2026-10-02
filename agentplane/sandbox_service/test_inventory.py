"""The relocated inventory reads retained Kubernetes state without an app or app database."""

import json
from copy import deepcopy

import pytest
import pytest_bazel

from agentplane.sandbox_service.binding_storage import write_binding
from agentplane.sandbox_service.kubernetes_views import SANDBOX_BINDING_ANNOTATION
from agentplane.sandbox_service.models import ProvisioningState, SandboxNotFoundError
from agentplane.sandbox_service.testing.kubernetes import ACCOUNT, SANDBOX, SANDBOX_UID, Cluster
from agentplane.sandbox_service.wire import sandbox_proto, sandbox_view
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE
from util.agent_sandbox import SANDBOXES_PLURAL

# gazelle:include_dep @pypi//protobuf


async def test_read_retained_sandbox_without_mutation(cluster: Cluster) -> None:
    before = deepcopy(cluster.fake.objects)
    view = await cluster.inventory.get(SANDBOX)
    assert view.uid == SANDBOX_UID
    assert view.service_account.namespace == SANDBOX_NAMESPACE
    assert view.service_account.name == ACCOUNT
    assert view.state is ProvisioningState.RUNNING
    assert cluster.fake.objects == before


@pytest.mark.parametrize(
    "raw",
    [
        '{"thread_defaults":{"harness":"HARNESS_CODEX","model":"retained-model","cwd":"/state/{session_id}",'
        '"instructions":"","setup_script":"printf setup"},"bootstrap":"printf boot"}',
        '{"bootstrap":"printf boot"}',
    ],
)
async def test_legacy_binding_storage_is_preserved_but_not_exposed(cluster: Cluster, raw: str) -> None:
    sandbox = cluster.fake.objects[SANDBOXES_PLURAL][SANDBOX]
    sandbox["metadata"].setdefault("annotations", {})[SANDBOX_BINDING_ANNOTATION] = raw
    before = deepcopy(cluster.fake.objects)
    view = await cluster.inventory.get(SANDBOX)
    binding = await cluster.inventory.binding(SANDBOX)
    assert binding is not None
    assert view.binding == binding
    assert json.loads(write_binding(binding)) == json.loads(raw)
    assert "thread_defaults" not in binding.model_dump()
    assert "session_defaults" in binding.model_dump()
    wire = sandbox_proto(view)
    assert wire.binding.DESCRIPTOR.fields_by_name["session_defaults"].number == 1
    assert "thread_defaults" not in wire.binding.DESCRIPTOR.fields_by_name
    assert sandbox_view(wire).binding == binding
    if binding.session_defaults is not None:
        assert binding.session_defaults.instructions == ""
        assert binding.session_defaults.proto_json("retained-session")["cwd"] == "/state/retained-session"
    assert cluster.fake.objects == before


async def test_suspended_sandbox_is_not_resumed(cluster: Cluster) -> None:
    cluster.fake.objects[SANDBOXES_PLURAL][SANDBOX]["spec"]["operatingMode"] = "Suspended"
    cluster.fake.pods.clear()
    before = deepcopy(cluster.fake.objects)
    view = await cluster.inventory.get(SANDBOX)
    assert view.state is ProvisioningState.SUSPENDED
    assert view.uid == SANDBOX_UID
    assert cluster.fake.objects == before


async def test_missing_sandbox_is_not_created(cluster: Cluster) -> None:
    before = deepcopy(cluster.fake.objects)
    with pytest.raises(SandboxNotFoundError):
        await cluster.inventory.get("test-missing")
    assert cluster.fake.objects == before


if __name__ == "__main__":
    pytest_bazel.main()
