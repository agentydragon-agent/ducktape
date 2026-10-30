"""Executable vm scenarios sharing one k3s stack."""

from __future__ import annotations

import pytest
import pytest_bazel

from agentplane.app.testing.client import Client
from agentplane.system_tests.cluster import Cluster
from agentplane.system_tests.sandbox import Sandboxes
from agentplane.system_tests.scenarios import runner_credentials, vm_sandbox
from agentplane.system_tests.scripted_upstream import ScriptedUpstream

pytestmark = pytest.mark.vm_sandboxes


@pytest.mark.vm_sandboxes
@pytest.mark.scripted_model
@pytest.mark.timeout(600)
async def test_vm_mtls_certificates_authenticate_both_harnesses(
    cluster: Cluster, client: Client, sandbox: Sandboxes, scripted: ScriptedUpstream
) -> None:
    await runner_credentials.vm_mtls_certificates_authenticate_both_harnesses(cluster, client, sandbox, scripted)


@pytest.mark.vm_sandboxes
@pytest.mark.scripted_model
async def test_vm_sandbox_scenarios(client: Client, sandbox: Sandboxes, scripted: ScriptedUpstream) -> None:
    await vm_sandbox.vm_sandbox_scenarios(client, sandbox, scripted)


if __name__ == "__main__":
    pytest_bazel.main()
