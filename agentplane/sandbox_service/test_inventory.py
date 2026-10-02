"""The relocated inventory reads retained Kubernetes state without an app or app database."""

from copy import deepcopy

import pytest
import pytest_bazel

from agentplane.sandbox_service.models import ProvisioningState, SandboxNotFoundError
from agentplane.sandbox_service.testing.kubernetes import ACCOUNT, SANDBOX, SANDBOX_UID, Cluster
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE
from util.agent_sandbox import SANDBOXES_PLURAL


async def test_read_retained_sandbox_without_mutation(cluster: Cluster) -> None:
    before = deepcopy(cluster.fake.objects)
    view = await cluster.inventory.get(SANDBOX)
    assert view.uid == SANDBOX_UID
    assert view.service_account.namespace == SANDBOX_NAMESPACE
    assert view.service_account.name == ACCOUNT
    assert view.state is ProvisioningState.RUNNING
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
