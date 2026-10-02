"""Protocol failure edges using a controllable gRPC peer, not an app or mocked RunnerClient."""

import asyncio
from collections.abc import AsyncIterator

import grpc
import pytest
import pytest_bazel

from agentplane.protocol import command_pb2, event_log_pb2, event_pb2
from agentplane.runner import protocol_pb2
from agentplane.runner.client import RunnerClient, RunnerError, StreamClosedError
from agentplane.sandbox_service.command_relay import admit_running_command

# gazelle:include_dep @pypi//protobuf
# gazelle:include_dep @pypi//grpcio


class ControlledRunner:
    def __init__(self) -> None:
        self.requests: asyncio.Queue[protocol_pb2.ClientMessage] = asyncio.Queue()
        self.responses: asyncio.Queue[protocol_pb2.ServerMessage | None] = asyncio.Queue()
        self.disconnected = asyncio.Event()
        self.harness_state = protocol_pb2.HARNESS_STATE_RUNNING

    async def attach(
        self, requests: AsyncIterator[protocol_pb2.ClientMessage], context: grpc.aio.ServicerContext
    ) -> AsyncIterator[protocol_pb2.ServerMessage]:
        del context
        try:
            first = await anext(requests)
            self.requests.put_nowait(first)
            yield protocol_pb2.ServerMessage(
                attached=protocol_pb2.Attached(session_id=first.open.session_id, harness_state=self.harness_state)
            )
            async for request in requests:
                self.requests.put_nowait(request)
                if request.HasField("detach"):
                    break
            while (response := await self.responses.get()) is not None:
                yield response
        finally:
            self.disconnected.set()


@pytest.fixture
async def peer() -> AsyncIterator[tuple[ControlledRunner, RunnerClient]]:
    peer = ControlledRunner()
    server = grpc.aio.server()
    server.add_generic_rpc_handlers(
        [
            grpc.method_handlers_generic_handler(
                "ducktape.agentplane.runner.v1.Runner",
                {
                    "Attach": grpc.stream_stream_rpc_method_handler(
                        peer.attach,
                        request_deserializer=protocol_pb2.ClientMessage.FromString,
                        response_serializer=protocol_pb2.ServerMessage.SerializeToString,
                    )
                },
            )
        ]
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    client = RunnerClient(f"127.0.0.1:{port}")
    try:
        yield peer, client
    finally:
        await client.close()
        await server.stop(0)


@pytest.fixture
def command() -> command_pb2.Command:
    return command_pb2.Command(
        command_id="test-notice", submit_input=command_pb2.SubmitInput(text="You have 7 messages")
    )


def admission(command: command_pb2.Command, cursor: int) -> event_log_pb2.EventEntry:
    return event_log_pb2.EventEntry(
        cursor=cursor,
        origin=event_log_pb2.EventOrigin(source_id="test-runner-log", sequence=cursor),
        event=event_pb2.Event(command_admitted=event_pb2.CommandAdmitted(command=command)),
    )


async def test_requires_exact_admission_and_preserves_receipt(
    peer: tuple[ControlledRunner, RunnerClient], command: command_pb2.Command
) -> None:
    async with asyncio.timeout(8):
        runner, client = peer
        async with asyncio.TaskGroup() as tasks:
            pending = tasks.create_task(
                admit_running_command(client, "test-session", command, after_cursor=11, timeout_s=5)
            )
            opened = await runner.requests.get()
            assert opened.open.session_id == "test-session"
            assert opened.open.follow.after_cursor == 11
            assert not opened.open.HasField("spec")
            assert not opened.open.HasField("setup_script")
            assert (await runner.requests.get()).command == command
            assert (await runner.requests.get()).HasField("detach")
            # Neither successful writes nor these unrelated receipts satisfy admission.
            assert not pending.done()
            other = command_pb2.Command(command_id="test-other", submit_input=command.submit_input)
            collision = command_pb2.Command(
                command_id=command.command_id, submit_input=command_pb2.SubmitInput(text="Other")
            )
            for cursor, candidate in enumerate([other, collision, command], start=12):
                runner.responses.put_nowait(protocol_pb2.ServerMessage(event_entry=admission(candidate, cursor)))
            assert await pending == admission(command, 14)
            await runner.disconnected.wait()


async def test_stopped_attachment_sends_no_command(
    peer: tuple[ControlledRunner, RunnerClient], command: command_pb2.Command
) -> None:
    async with asyncio.timeout(8):
        runner, client = peer
        runner.harness_state = protocol_pb2.HARNESS_STATE_STOPPED
        with pytest.raises(RunnerError, match="session is stopped"):
            await admit_running_command(client, "test-session", command, after_cursor=0, timeout_s=5)
        await runner.disconnected.wait()
        assert (await runner.requests.get()).HasField("open")
        assert runner.requests.empty()


async def test_timeout_cancels_attachment(
    peer: tuple[ControlledRunner, RunnerClient], command: command_pb2.Command
) -> None:
    async with asyncio.timeout(8):
        runner, client = peer
        with pytest.raises(TimeoutError):
            await admit_running_command(client, "test-session", command, after_cursor=0, timeout_s=0.01)
        await runner.disconnected.wait()


async def test_caller_cancellation_cancels_attachment(
    peer: tuple[ControlledRunner, RunnerClient], command: command_pb2.Command
) -> None:
    async with asyncio.timeout(8):
        runner, client = peer
        async with asyncio.TaskGroup() as tasks:
            pending = tasks.create_task(
                admit_running_command(client, "test-session", command, after_cursor=0, timeout_s=5)
            )
            assert (await runner.requests.get()).HasField("open")
            assert (await runner.requests.get()).command == command
            assert (await runner.requests.get()).HasField("detach")
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await runner.disconnected.wait()


@pytest.mark.parametrize("error", [None, "test journal failure"])
async def test_stream_end_or_error_is_not_admission(
    peer: tuple[ControlledRunner, RunnerClient], command: command_pb2.Command, error: str | None
) -> None:
    async with asyncio.timeout(8):
        runner, client = peer
        runner.responses.put_nowait(protocol_pb2.ServerMessage(error=error) if error else None)
        expected = RunnerError if error else StreamClosedError
        with pytest.raises(expected):
            await admit_running_command(client, "test-session", command, after_cursor=0, timeout_s=5)
        await runner.disconnected.wait()


if __name__ == "__main__":
    pytest_bazel.main()
