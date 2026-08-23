"""Codex through the real shared runner transport and its concrete RuntimeAdapter."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest_bazel

from haku.console.x.codex_app_server.runtime import CodexRuntimeAdapter
from haku.console.x.conversation_events import ConversationEvent, ItemSegment, MessageCompleted, TurnCompleted
from haku.console.x.runtime import RuntimeLaunch
from haku.runtime.x.bridge.client import RecordedFrame
from haku.runtime.x.bridge.codex_options import codex_app_server_backend
from haku.runtime.x.bridge.protocol import CONSOLE_TO_RUNNER, HarnessFrame, HarnessLaunch, Hello
from haku.runtime.x.bridge.runner import (
    Outbound,
    OutboundLog,
    _drain_cli,
    _serve_console,
    _shutdown,
    _start_cli,
    bridge_websocket_to_cli,
)
from util.bazel.runfiles import get_required_path

STUB_CODEX = "_main/haku/console/x/codex_app_server/testing/stub_codex_bin"


class MemoryWebSocket:
    def __init__(self, incoming: anyio.abc.ObjectReceiveStream[str], outgoing: anyio.abc.ObjectSendStream[str]):
        self._incoming = incoming
        self._outgoing = outgoing

    async def send_text(self, data: str) -> None:
        await self._outgoing.send(data)

    async def receive_text(self) -> str:
        try:
            return await self._incoming.receive()
        except anyio.EndOfStream as error:
            raise EOFError from error

    async def close(self) -> None:
        await self._outgoing.aclose()
        await self._incoming.aclose()


def _sockets() -> tuple[MemoryWebSocket, MemoryWebSocket]:
    left_send, left_receive = anyio.create_memory_object_stream[str](64)
    right_send, right_receive = anyio.create_memory_object_stream[str](64)
    return MemoryWebSocket(right_receive, left_send), MemoryWebSocket(left_receive, right_send)


class Sink:
    def __init__(self) -> None:
        self.next = 1
        self.runner_frames: dict[int, int] = {}

    async def sent(self, frame: HarnessFrame) -> int:
        result, self.next = self.next, self.next + 1
        return result

    async def received(self, frame: HarnessFrame) -> RecordedFrame:
        if frame.seq is not None and frame.seq in self.runner_frames:
            return RecordedFrame(fresh=False, frame_seq=self.runner_frames[frame.seq])
        result, self.next = self.next, self.next + 1
        if frame.seq is not None:
            self.runner_frames[frame.seq] = result
        return RecordedFrame(fresh=True, frame_seq=result)

    @property
    def highest_runner_seq(self) -> int | None:
        return max(self.runner_frames, default=None)


async def test_codex_implements_the_same_adapter_runner_turn_loop_shape_as_claude(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    console_socket, runner_socket = _sockets()
    adapter = CodexRuntimeAdapter()
    client = adapter.client(
        console_socket,
        RuntimeLaunch(
            cwd=str(tmp_path),
            environment={"HAKU_STUB_STATE": str(state)},
            mcp_servers={},
            appended_system_prompt="you are Haku",
            resume_from=None,
        ),
        None,
        Sink(),
    )

    async def runner() -> None:
        await runner_socket.send_text(Hello().model_dump_json())
        launch = CONSOLE_TO_RUNNER.validate_json(await runner_socket.receive_text())
        assert isinstance(launch, HarnessLaunch)
        await bridge_websocket_to_cli(
            runner_socket, backend=codex_app_server_backend(get_required_path(STUB_CODEX)), launch=launch
        )

    events: list[ConversationEvent] = []
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(runner)
        await client.connect()
        await client.query("hello")
        handler = adapter.turn_handler()
        with anyio.fail_after(10):
            async for received in client.frames():
                effects = handler.apply(frame_seq=received.frame_seq, frame=received.envelope)
                events.extend(effects.events)
                if effects.completion is not None:
                    break
        await client.aclose()

    assert [event.text for event in events if isinstance(event, ItemSegment)] == ["re: hello"]
    assert isinstance(events[-1], TurnCompleted)
    assert (state / "system-prompts.jsonl").read_text() == '"you are Haku"\n'


async def test_a_replacement_console_adopts_the_active_turn_in_the_same_runner_process(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    first_console, first_runner = _sockets()
    second_console, second_runner = _sockets()
    second_ready = anyio.Event()
    first_finished = anyio.Event()
    adapter, sink = CodexRuntimeAdapter(), Sink()
    first_client = adapter.client(
        first_console,
        RuntimeLaunch(
            cwd=str(tmp_path),
            environment={"HAKU_STUB_STATE": str(state)},
            mcp_servers={},
            appended_system_prompt="you are Haku",
            resume_from=None,
        ),
        None,
        sink,
    )

    async def runner_session() -> None:
        await first_runner.send_text(Hello().model_dump_json())
        first_launch = CONSOLE_TO_RUNNER.validate_json(await first_runner.receive_text())
        assert isinstance(first_launch, HarnessLaunch)
        backend = codex_app_server_backend(get_required_path(STUB_CODEX))
        process = await _start_cli(backend, first_launch)
        outbound_sender, outbound_receiver = anyio.create_memory_object_stream[Outbound](64)
        log = OutboundLog()
        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(_drain_cli, process, outbound_sender, tasks.cancel_scope)
                await _serve_console(first_runner, process, outbound_receiver, log, first_launch.resume_from)
                first_finished.set()
                await second_ready.wait()
                await second_runner.send_text(Hello().model_dump_json())
                second_launch = CONSOLE_TO_RUNNER.validate_json(await second_runner.receive_text())
                assert isinstance(second_launch, HarnessLaunch)
                await _serve_console(second_runner, process, outbound_receiver, log, second_launch.resume_from)
                tasks.cancel_scope.cancel()
        finally:
            await _shutdown(process)

    events: list[ConversationEvent] = []
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(runner_session)
        await first_client.connect()
        await first_client.query("[hold] hello")
        first_handler = adapter.turn_handler()
        message_completed = False
        with anyio.fail_after(10):
            async for received in first_client.frames():
                effects = first_handler.apply(frame_seq=received.frame_seq, frame=received.envelope)
                events.extend(effects.events)
                if any(isinstance(event, MessageCompleted) for event in effects.events):
                    message_completed = True
                if received.envelope.frame.get("method") == "haku/stubHeld":
                    assert message_completed
                    break
        cursor = sink.highest_runner_seq
        assert cursor is not None
        await first_client.aclose()
        await first_finished.wait()

        second_client = adapter.client(
            second_console,
            RuntimeLaunch(
                cwd=str(tmp_path),
                environment={"HAKU_STUB_STATE": str(state)},
                mcp_servers={},
                appended_system_prompt="you are Haku",
                resume_from=cursor,
            ),
            None,
            sink,
        )
        second_ready.set()
        adopted = await second_client.connect()
        assert adopted["activeTurnId"] == "turn-1"
        (state / "release").write_text("")
        second_handler = adapter.turn_handler()
        with anyio.fail_after(10):
            async for received in second_client.frames():
                effects = second_handler.apply(frame_seq=received.frame_seq, frame=received.envelope)
                events.extend(effects.events)
                if effects.completion is not None:
                    break
        await second_client.aclose()

    assert [event.text for event in events if isinstance(event, ItemSegment)] == ["re: hello"]
    assert sum(isinstance(event, MessageCompleted) for event in events) == 1
    assert sum(isinstance(event, TurnCompleted) for event in events) == 1


if __name__ == "__main__":
    pytest_bazel.main()
