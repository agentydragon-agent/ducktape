"""Executable pod scenarios sharing one k3s stack."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_bazel

# gazelle:include_dep @pypi//protobuf
from agentplane.app.testing.client import Client
from agentplane.proto import runner_pb2
from agentplane.system_tests.agent import TURN_SECONDS
from agentplane.system_tests.conftest import Sandboxes
from agentplane.system_tests.executor import Executor
from agentplane.system_tests.scenarios import (
    agent_messaging,
    egress,
    launch_presets,
    runner_credentials,
    session_instructions,
    storage,
    suspend_resume,
    thread_stream,
)
from agentplane.system_tests.scripted_upstream import ScriptedUpstream


@pytest.fixture
async def http(base_url: str, token: str) -> AsyncIterator[httpx.AsyncClient]:
    """The app as a browser reaches it: its raw responses and server-sent events."""
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(thread_stream.REQUEST_SECONDS, read=TURN_SECONDS),
    ) as opened:
        yield opened


@pytest.fixture
def executor() -> Executor:
    return Executor(template="runner", cwd="/state/work")


@pytest.fixture
def storage_layout() -> storage.StorageLayout:
    return storage.StorageLayout.POD_DIRECTORY


@pytest.mark.scripted_model
async def test_an_agent_messages_another_which_reads_and_acknowledges_it(
    client: Client, sandbox: Sandboxes, harness: runner_pb2.Harness, offered_model: str, scripted: ScriptedUpstream
) -> None:
    await agent_messaging.an_agent_messages_another_which_reads_and_acknowledges_it(
        client, sandbox, harness, offered_model, scripted
    )


@pytest.mark.scripted_model
async def test_a_policy_granted_after_the_sandbox_is_running_takes_effect(
    client: Client, sandbox: Sandboxes, harness: runner_pb2.Harness, offered_model: str, scripted: ScriptedUpstream
) -> None:
    await egress.a_policy_granted_after_the_sandbox_is_running_takes_effect(
        client, sandbox, harness, offered_model, scripted
    )


@pytest.mark.scripted_model
async def test_the_model_call_itself_goes_through_the_proxy(
    client: Client, sandbox: Sandboxes, harness: runner_pb2.Harness, offered_model: str, scripted: ScriptedUpstream
) -> None:
    await egress.the_model_call_itself_goes_through_the_proxy(client, sandbox, harness, offered_model, scripted)


@pytest.mark.scripted_model
async def test_a_preset_launches_an_initialized_editable_codex_thread(
    client: Client, sandbox: Sandboxes, scripted: ScriptedUpstream
) -> None:
    await launch_presets.a_preset_launches_an_initialized_editable_codex_thread(client, sandbox, scripted)


async def test_cert_manager_reissues_a_deleted_tls_secret() -> None:
    await runner_credentials.cert_manager_reissues_a_deleted_tls_secret()


@pytest.mark.scripted_model
@pytest.mark.timeout(600)
async def test_pod_mtls_session_survives_replacement_and_keeps_history(
    client: Client, sandbox: Sandboxes, harness: runner_pb2.Harness, offered_model: str, scripted: ScriptedUpstream
) -> None:
    await runner_credentials.pod_mtls_session_survives_replacement_and_keeps_history(
        client, sandbox, harness, offered_model, scripted
    )


@pytest.mark.scripted_model
async def test_the_standing_instruction_reaches_the_model_and_only_in_its_own_session(
    client: Client, sandbox: Sandboxes, harness: runner_pb2.Harness, offered_model: str, scripted: ScriptedUpstream
) -> None:
    await session_instructions.the_standing_instruction_reaches_the_model_and_only_in_its_own_session(
        client, sandbox, harness, offered_model, scripted
    )


async def test_fresh_workspace_storage_survives_replacement(
    client: Client, executor: Executor, storage_layout: storage.StorageLayout
) -> None:
    await storage.fresh_workspace_storage_survives_replacement(client, executor, storage_layout)


@pytest.mark.scripted_model
async def test_codex_standing_instructions_after_suspend_and_compact(
    client: Client, sandbox: Sandboxes, scripted: ScriptedUpstream
) -> None:
    await suspend_resume.codex_standing_instructions_after_suspend_and_compact(client, sandbox, scripted)


@pytest.mark.scripted_model
async def test_two_harness_threads_keep_their_context_after_sandbox_suspend_resume(
    client: Client, sandbox: Sandboxes, scripted: ScriptedUpstream, executor: Executor
) -> None:
    await suspend_resume.two_harness_threads_keep_their_context_after_sandbox_suspend_resume(
        client, sandbox, scripted, executor
    )


async def test_an_unknown_thread_is_not_found(http: httpx.AsyncClient) -> None:
    await thread_stream.an_unknown_thread_is_not_found(http)


@pytest.mark.scripted_model
async def test_every_tab_follows_one_log_and_a_reconnect_resumes_after_its_last_event(
    client: Client,
    http: httpx.AsyncClient,
    sandbox: Sandboxes,
    harness: runner_pb2.Harness,
    offered_model: str,
    scripted: ScriptedUpstream,
) -> None:
    await thread_stream.every_tab_follows_one_log_and_a_reconnect_resumes_after_its_last_event(
        client, http, sandbox, harness, offered_model, scripted
    )


@pytest.mark.scripted_model
async def test_turns_nobody_watches_are_archived_and_a_failed_one_leaves_the_next_input_its_own_turn(
    client: Client,
    http: httpx.AsyncClient,
    sandbox: Sandboxes,
    harness: runner_pb2.Harness,
    offered_model: str,
    scripted: ScriptedUpstream,
) -> None:
    await thread_stream.turns_nobody_watches_are_archived_and_a_failed_one_leaves_the_next_input_its_own_turn(
        client, http, sandbox, harness, offered_model, scripted
    )


if __name__ == "__main__":
    pytest_bazel.main()
