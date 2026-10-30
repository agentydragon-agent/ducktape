"""Executable vm scenarios sharing one k3s stack."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_bazel

from agentplane.app.testing.client import Client
from agentplane.system_tests.cluster import Cluster
from agentplane.system_tests.executor import Executor
from agentplane.system_tests.sandbox import Sandboxes
from agentplane.system_tests.scenarios import central_sampler, runner_credentials, runner_systemd, vm_sandbox
from agentplane.system_tests.scripted_upstream import ScriptedUpstream

pytestmark = pytest.mark.vm_sandboxes


@pytest.mark.vm_sandboxes
@pytest.mark.scripted_model
@pytest.mark.timeout(600)
async def test_vm_credentials_and_central_sampler(
    cluster: Cluster, tmp_path: Path, client: Client, sandbox: Sandboxes, scripted: ScriptedUpstream
) -> None:
    # pytest-asyncio runs separate cases sequentially. Share this case's fixtures so the sampler
    # boots alongside the two credential guests, keeping the peak at three independent VMs.
    async with asyncio.TaskGroup() as scenarios:
        scenarios.create_task(
            runner_credentials.vm_mtls_certificates_authenticate_both_harnesses(cluster, client, sandbox, scripted)
        )
        scenarios.create_task(
            central_sampler.dispatcher_central_setup_tool_and_retained_answer(
                cluster,
                tmp_path,
                scripted,
                Executor(template="runner-vm", cwd="/state/workspaces/accept"),
                central_sampler.VM_EXECUTION,
            )
        )


@pytest.mark.vm_sandboxes
@pytest.mark.scripted_model
async def test_vm_sandbox_scenarios(client: Client, sandbox: Sandboxes, scripted: ScriptedUpstream) -> None:
    await vm_sandbox.vm_sandbox_scenarios(client, sandbox, scripted)


async def test_real_systemd_supervision(sandbox: Sandboxes) -> None:
    await runner_systemd.real_systemd_supervision(sandbox)


if __name__ == "__main__":
    pytest_bazel.main()
