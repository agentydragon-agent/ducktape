"""Exercise the extracted backend path with real runners and both native harnesses, without the app."""

import pytest
import pytest_bazel

from agentplane.protocol import command_pb2
from agentplane.runner import protocol_pb2
from agentplane.runner.client import RunnerClient, RunnerError
from agentplane.runner.testing import events
from agentplane.runner.testing.scripted_model import ScriptedModel, Text
from agentplane.sandbox_service.command_relay import admit_running_command

# gazelle:include_dep @pypi//protobuf


async def test_admission_and_replay_do_not_wait_for_model_reply(
    client: RunnerClient, model: ScriptedModel, spec: protocol_pb2.SessionSpec
) -> None:
    command = command_pb2.Command(
        command_id="test-notice", submit_input=command_pb2.SubmitInput(text="Reply with exactly: NOTICE_OK")
    )
    async with await client.attach("test-notifications", spec=spec) as observer:
        receipt = await admit_running_command(
            client, "test-notifications", command, after_cursor=observer.cursor, timeout_s=15
        )
        assert receipt.event.command_admitted.command == command
        assert receipt.origin.source_id
        assert receipt.origin.sequence > 0
        # Replay of the same command must return the original receipt, before native completion.
        replay = await admit_running_command(client, "test-notifications", command, after_cursor=0, timeout_s=15)
        assert replay == receipt
        await model.reply(await model.request(), Text("NOTICE_OK"))
        await observer.until(events.turn_completed)
        assert events.of_kind(observer.seen, "command_admitted") == [receipt]
        confirmations = events.of_kind(observer.seen, "harness_user_message_confirmed")
        assert any(
            command.command_id in entry.event.harness_user_message_confirmed.origin_command_ids
            for entry in confirmations
        )


async def test_stopped_session_is_not_resumed(client: RunnerClient, spec: protocol_pb2.SessionSpec) -> None:
    observer = await client.attach("test-stopped", spec=spec)
    try:
        await observer.stop_runner_session("test-stop")
        await observer.until(events.is_kind("harness_exited"))
        # Stop closes this feed; consume EOF rather than racing it with a Detach write.
        await observer.drain_until_end()
    finally:
        observer.cancel()
    command = command_pb2.Command(command_id="test-no-wake", submit_input=command_pb2.SubmitInput(text="Do not wake"))
    with pytest.raises(RunnerError, match="session is stopped"):
        await admit_running_command(client, "test-stopped", command, after_cursor=0, timeout_s=15)
    observer = await client.attach("test-stopped")
    try:
        assert observer.attached.harness_state == protocol_pb2.HARNESS_STATE_STOPPED
        await observer.drain_until_end()
    finally:
        observer.cancel()
    assert all(
        entry.event.command_admitted.command != command for entry in events.of_kind(observer.seen, "command_admitted")
    )


async def test_unknown_session_is_not_created(client: RunnerClient) -> None:
    command = command_pb2.Command(command_id="test-missing", submit_input=command_pb2.SubmitInput(text="No session"))
    with pytest.raises(RunnerError, match="does not exist"):
        await admit_running_command(client, "test-unknown", command, after_cursor=0, timeout_s=15)
    assert not await client.list_sessions()


if __name__ == "__main__":
    pytest_bazel.main()
