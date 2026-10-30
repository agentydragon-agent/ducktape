"""Executable vm_manual scenarios sharing one k3s stack."""

from __future__ import annotations

import pytest
import pytest_bazel

from agentplane.app.testing.client import Client
from agentplane.system_tests.conftest import Sandboxes
from agentplane.system_tests.executor import Executor
from agentplane.system_tests.k3s.stack import Stack
from agentplane.system_tests.scenarios import storage, suspend_resume, vm_workspace_ownership
from agentplane.system_tests.scripted_upstream import ScriptedUpstream

pytestmark = pytest.mark.vm_sandboxes


async def test_fresh_workspace_storage_survives_replacement(
    client: Client, executor: Executor, storage_layout: storage.StorageLayout
) -> None:
    await storage.fresh_workspace_storage_survives_replacement(client, executor, storage_layout)


@pytest.fixture
def executor(deployment: Stack) -> Executor:
    return deployment.executor("runner-vm", cwd="/state/workspaces/accept")


@pytest.fixture
def storage_layout() -> storage.StorageLayout:
    return storage.StorageLayout.VM_RAW


@pytest.mark.scripted_model
async def test_two_harness_threads_keep_their_context_after_sandbox_suspend_resume(
    client: Client, sandbox: Sandboxes, scripted: ScriptedUpstream, executor: Executor
) -> None:
    await suspend_resume.two_harness_threads_keep_their_context_after_sandbox_suspend_resume(
        client, sandbox, scripted, executor
    )


@pytest.mark.vm_sandboxes
async def test_fresh_vm_session_workspace_is_created_for_harness_identity(client: Client, sandbox: Sandboxes) -> None:
    await vm_workspace_ownership.fresh_vm_session_workspace_is_created_for_harness_identity(client, sandbox)


if __name__ == "__main__":
    pytest_bazel.main()
