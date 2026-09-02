"""The same streamed gRPC client drives both pinned native harnesses."""

from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import grpc
import pytest
import pytest_bazel

from x.agentplane.runner import RunnerConfig, serve

protocol_pb2: Any = importlib.import_module("x.agentplane.protocol_pb2")

pytest_plugins = (
    "x.agentplane.capture.replay_fixtures",
    "x.agentplane.capture.providers.claude.replay_fixtures",
    "x.agentplane.capture.providers.codex.replay_fixtures",
)


@dataclass(frozen=True, slots=True)
class Case:
    provider: str
    replay: Any
    provider_enum: int


def _case(provider: str, claude_replay: Any, codex_replay: Any) -> Case:
    if provider == "claude":
        return Case(provider, claude_replay, protocol_pb2.PROVIDER_CLAUDE)
    return Case(provider, codex_replay, protocol_pb2.PROVIDER_CODEX)


def _input(input_id: str, text: str, mode: int = 0) -> Any:
    return protocol_pb2.ClientMessage(input=protocol_pb2.Input(input_id=input_id, text=text, mode=mode))


async def _run(case: Case, server: Any, tmp_path: Any, commands: list[Any], *, terminals: int = 1) -> list[Any]:
    endpoint = f"http://127.0.0.1:{server.server_port}"
    environment = case.replay.environment(endpoint)
    config = RunnerConfig(
        claude_binary=case.replay.binary if case.provider == "claude" else "claude",
        codex_binary=case.replay.binary if case.provider == "codex" else "codex",
        environment=environment,
        claude_command_builder=lambda _binary, _model, resume_id: case.replay.command(resume_id=resume_id),
        codex_command_builder=lambda _binary, _endpoint: case.replay.command(endpoint=_endpoint),
    )
    runner, port = await serve(config)
    done = [asyncio.Event() for _ in range(terminals)]
    observations: list[Any] = []

    async def request_source() -> AsyncIterator[Any]:
        yield protocol_pb2.ClientMessage(
            start=protocol_pb2.Start(
                provider=case.provider_enum,
                cwd=str(tmp_path),
                model="chatgpt/oai-responses/gpt-5.6-luna",
                reasoning_effort="low",
                llm_endpoint=endpoint,
                persist=False,
            )
        )
        for index, command in enumerate(commands):
            yield command
            if index < terminals:
                await done[index].wait()

    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        rpc = channel.stream_stream(
            "/ducktape.agentplane.v1.HarnessRunner/Connect",
            request_serializer=protocol_pb2.ClientMessage.SerializeToString,
            response_deserializer=protocol_pb2.ServerMessage.FromString,
        )
        async for response in rpc(request_source()):
            if response.HasField("event"):
                event = response.event
                observations.append(event)
                if event.WhichOneof("observation") == "turn_completed":
                    index = sum(item.WhichOneof("observation") == "turn_completed" for item in observations) - 1
                    if index < len(done):
                        done[index].set()
            elif response.HasField("protocol_error"):
                raise AssertionError(response.protocol_error)
    finally:
        await channel.close()
        await runner.stop(0)
    return observations


def _events(observations: list[Any], kind: str) -> list[Any]:
    return [event for event in observations if event.WhichOneof("observation") == kind]


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_one_shared_streamed_client_drives_baseline(
    provider, claude_replay, codex_replay, replay_server, tmp_path
) -> None:
    case = _case(provider, claude_replay, codex_replay)
    with replay_server(provider, "baseline") as upstream:
        observations = await _run(
            case, upstream, tmp_path, [_input("input-1", "Reply with exactly: CAPTURE_BASELINE_OK")]
        )
        ready = _events(observations, "ready")[-1]
        assert ready.ready.provider == case.provider_enum
        assert "submit" in ready.ready.capabilities
        assert _events(observations, "text_delta")
        assert _events(observations, "turn_completed")[-1].turn_completed.status == protocol_pb2.TURN_STATUS_COMPLETED
        native = _events(observations, "native")
        assert native
        assert all(json.loads(event.native.payload_json) for event in native)
        upstream.assert_consumed()


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_shared_client_preserves_tool_lifecycle(
    provider, claude_replay, codex_replay, replay_server, tmp_path
) -> None:
    case = _case(provider, claude_replay, codex_replay)
    with replay_server(provider, "shell") as upstream:
        observations = await _run(
            case, upstream, tmp_path, [_input("input-1", "Use the shell probe and report its outcomes.")]
        )
        assert _events(observations, "tool_call_started")
        assert _events(observations, "tool_call_completed")
        assert _events(observations, "tool_call_delta") or _events(observations, "native")
        upstream.assert_consumed()


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_shared_client_reports_provider_observed_llm_recovery(
    provider, claude_replay, codex_replay, replay_server, tmp_path
) -> None:
    case = _case(provider, claude_replay, codex_replay)
    with replay_server(provider, "post_exhaustion_follow_up") as upstream:
        observations = await _run(
            case,
            upstream,
            tmp_path,
            [
                _input("input-1", "Reply with exactly: POST_EXHAUSTION_FIRST_OK"),
                _input("input-2", "Reply with exactly: POST_EXHAUSTION_FOLLOW_UP_OK"),
            ],
            terminals=2,
        )
        completions = _events(observations, "turn_completed")
        assert len(completions) == 2
        assert completions[0].turn_completed.status == protocol_pb2.TURN_STATUS_FAILED
        assert completions[1].turn_completed.status == protocol_pb2.TURN_STATUS_COMPLETED
        assert _events(observations, "native")
        upstream.assert_consumed()


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_shared_interrupt_command_has_explicit_terminal_outcome(
    provider, claude_replay, codex_replay, replay_server, tmp_path
) -> None:
    case = _case(provider, claude_replay, codex_replay)
    with replay_server(provider, "interrupt") as upstream:
        endpoint = f"http://127.0.0.1:{upstream.server_port}"
        environment = case.replay.environment(endpoint)
        config = RunnerConfig(
            claude_binary=case.replay.binary if provider == "claude" else "claude",
            codex_binary=case.replay.binary if provider == "codex" else "codex",
            environment=environment,
            claude_command_builder=lambda _binary, _model, resume_id: case.replay.command(resume_id=resume_id),
            codex_command_builder=lambda _binary, _endpoint: case.replay.command(endpoint=_endpoint),
        )
        runner, port = await serve(config)
        active = asyncio.Event()
        terminal = asyncio.Event()
        observations: list[Any] = []

        async def source() -> AsyncIterator[Any]:
            yield protocol_pb2.ClientMessage(
                start=protocol_pb2.Start(
                    provider=case.provider_enum,
                    cwd=str(tmp_path),
                    model="chatgpt/oai-responses/gpt-5.6-luna",
                    reasoning_effort="low",
                    llm_endpoint=endpoint,
                )
            )
            yield _input("input-1", "Use the long-running shell probe and do not answer early.")
            await active.wait()
            yield protocol_pb2.ClientMessage(
                interrupt=protocol_pb2.Interrupt(command_id="interrupt-1", reason="test", cancel_queued=False)
            )
            await terminal.wait()

        channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
        try:
            rpc = channel.stream_stream(
                "/ducktape.agentplane.v1.HarnessRunner/Connect",
                request_serializer=protocol_pb2.ClientMessage.SerializeToString,
                response_deserializer=protocol_pb2.ServerMessage.FromString,
            )
            async for response in rpc(source()):
                if not response.HasField("event"):
                    continue
                event = response.event
                observations.append(event)
                if event.WhichOneof("observation") == "turn_started":
                    active.set()
                if event.WhichOneof("observation") == "turn_completed":
                    terminal.set()
        finally:
            await channel.close()
            await runner.stop(0)
        assert _events(observations, "turn_completed")[-1].turn_completed.status == protocol_pb2.TURN_STATUS_INTERRUPTED
        upstream.assert_consumed()


if __name__ == "__main__":
    pytest_bazel.main()
