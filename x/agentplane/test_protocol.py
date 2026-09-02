"""The same streamed gRPC client drives both pinned native harnesses."""

from __future__ import annotations

import asyncio
import importlib
import os
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import grpc
import pytest
import pytest_bazel

from util.bazel.runfiles import get_required_path
from x.agentplane.harness_tests.claude import anthropic_sse, harness as claude_harness
from x.agentplane.harness_tests.claude.requests import MessagesRequest
from x.agentplane.harness_tests.codex import harness as codex_harness, responses_sse
from x.agentplane.harness_tests.codex.requests import ResponsesRequest
from x.agentplane.harness_tests.scripted_upstream import ScriptedUpstream
from x.agentplane.native import process as native_process
from x.agentplane.native.claude import scenarios as claude_scenarios
from x.agentplane.native.codex import scenarios as codex_scenarios
from x.agentplane.runner import RunnerConfig, serve as serve_runner

protocol_pb2: Any = importlib.import_module("x.agentplane.protocol_pb2")


@pytest.fixture
def upstream() -> Iterator[ScriptedUpstream]:
    with native_process.serve(ScriptedUpstream()) as server:
        yield server


@dataclass(frozen=True, slots=True)
class Case:
    provider: str
    provider_enum: int
    binary: str
    model: str
    command_builder: Callable[..., list[str]]
    environment_builder: Callable[[str, Path], dict[str, str]]


def _claude_command(binary: str, model: str, continuation_id: str | None) -> list[str]:
    return [claude_harness._dynamic_loader(), *claude_scenarios.command(binary, model=model, resume_id=continuation_id)]


def _claude_environment(endpoint: str, root: Path) -> dict[str, str]:
    return claude_scenarios.environment(endpoint=endpoint, token="test-key", config_dir=str(root / ".claude"))


def _codex_environment(endpoint: str, root: Path) -> dict[str, str]:
    return codex_scenarios.environment(endpoint=f"{endpoint}/v1", token="test-key", codex_home=str(root / ".codex"))


@pytest.fixture
def cases(tmp_path: Path) -> dict[str, Case]:
    (tmp_path / "home").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".codex").mkdir()
    return {
        "claude": Case(
            "claude",
            protocol_pb2.PROVIDER_CLAUDE,
            str(get_required_path("claude_code_cli_linux_x64/claude")),
            claude_harness.MODEL,
            _claude_command,
            _claude_environment,
        ),
        "codex": Case(
            "codex",
            protocol_pb2.PROVIDER_CODEX,
            str(get_required_path("agentplane_codex_cli_linux_x64/bin/codex")),
            codex_harness.MODEL,
            lambda binary, _model, _continuation_id: codex_scenarios.command(binary, endpoint="unused"),
            _codex_environment,
        ),
    }


def _runner_config(case: Case, upstream: ScriptedUpstream, root: Path) -> RunnerConfig:
    endpoint = upstream.origin
    base_environment = {
        "HOME": str(root / "home"),
        "NO_PROXY": "127.0.0.1,localhost",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    return RunnerConfig(
        claude_binary=case.binary if case.provider == "claude" else "unused-claude",
        codex_binary=case.binary if case.provider == "codex" else "unused-codex",
        environment={**base_environment, **case.environment_builder(endpoint, root)},
        claude_command_builder=case.command_builder,
        codex_command_builder=lambda binary, _endpoint: codex_scenarios.command(binary, endpoint=endpoint),
    )


def _input(input_id: str, text: str, mode: int = 0) -> Any:
    return protocol_pb2.ClientMessage(input=protocol_pb2.Input(input_id=input_id, text=text, mode=mode))


async def _collect(
    case: Case, upstream: ScriptedUpstream, root: Path, commands: list[Any], *, terminals: int = 1
) -> list[Any]:
    runner, port = await serve_runner(_runner_config(case, upstream, root))
    done = [asyncio.Event() for _ in range(terminals)]
    observations: list[Any] = []
    endpoint = upstream.origin

    async def request_source() -> AsyncIterator[Any]:
        yield protocol_pb2.ClientMessage(
            start=protocol_pb2.Start(
                provider=case.provider_enum,
                cwd=str(root),
                model=case.model,
                reasoning_effort="low",
                llm_endpoint=endpoint,
                persist=False,
            )
        )
        for index, command in enumerate(commands):
            yield command
            if index < terminals:
                await done[index].wait()
        yield protocol_pb2.ClientMessage(close=protocol_pb2.Close(reason="test complete"))

    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        rpc = channel.stream_stream(
            "/ducktape.agentplane.v1.HarnessRunner/Connect",
            request_serializer=protocol_pb2.ClientMessage.SerializeToString,
            response_deserializer=protocol_pb2.ServerMessage.FromString,
        )
        call = rpc(request_source())
        async for response in call:
            if response.HasField("protocol_error"):
                raise AssertionError(response.protocol_error)
            if not response.HasField("event"):
                continue
            event = response.event
            observations.append(event)
            if event.WhichOneof("observation") == "turn_completed":
                index = sum(item.WhichOneof("observation") == "turn_completed" for item in observations) - 1
                if index < len(done):
                    done[index].set()
    finally:
        await channel.close()
        await runner.stop(0)
    return observations


def _events(observations: list[Any], kind: str) -> list[Any]:
    return [event for event in observations if event.WhichOneof("observation") == kind]


async def _next_request(upstream: ScriptedUpstream) -> Any:
    return await asyncio.to_thread(upstream.next_request)


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_one_shared_streamed_client_drives_baseline(
    provider: str, cases: dict[str, Case], upstream: ScriptedUpstream, tmp_path: Path
) -> None:
    case = cases[provider]
    task = asyncio.create_task(
        _collect(case, upstream, tmp_path, [_input("input-1", "Reply with exactly: BASELINE_OK")])
    )
    raw = await _next_request(upstream)
    if provider == "claude":
        claude_request = MessagesRequest.parse(raw)
        assert claude_request.stream is True
        assert claude_request.texts("user")[-1] == "Reply with exactly: BASELINE_OK"
        upstream.respond(raw, anthropic_sse.message_stream([anthropic_sse.Text("BASELINE_OK")], model=case.model))
    else:
        codex_request = ResponsesRequest.parse(raw)
        assert codex_request.stream is True
        assert codex_request.messages("user")[-1].text == "Reply with exactly: BASELINE_OK"
        upstream.respond(raw, responses_sse.response_stream([responses_sse.Message("BASELINE_OK")], model=case.model))
    observations = await task
    assert _events(observations, "ready")[-1].ready.provider == case.provider_enum
    assert _events(observations, "input_accepted")[-1].input_accepted.input_id == "input-1"
    assert _events(observations, "text_delta")
    assert _events(observations, "turn_completed")[-1].turn_completed.status == protocol_pb2.TURN_STATUS_COMPLETED
    native = _events(observations, "native")
    assert native
    assert all(event.source_event_sequences == [] for event in native)
    assert any(event.source_event_sequences for event in _events(observations, "text_delta"))
    assert _events(observations, "session_closed")[-1].session_closed.reason == "test complete"
    assert [event.sequence for event in observations] == sorted(event.sequence for event in observations)
    upstream.assert_quiescent()


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_shared_client_preserves_tool_lifecycle(
    provider: str, cases: dict[str, Case], upstream: ScriptedUpstream, tmp_path: Path
) -> None:
    case = cases[provider]
    task = asyncio.create_task(
        _collect(case, upstream, tmp_path, [_input("input-1", "Run the tool and report TOOL_DONE.")])
    )
    first = await _next_request(upstream)
    if provider == "claude":
        upstream.respond(
            first,
            anthropic_sse.message_stream(
                [anthropic_sse.ToolUse("toolu_test", "Bash", {"command": "printf TOOL_RESULT"})], model=case.model
            ),
        )
        second = await _next_request(upstream)
        claude_request = MessagesRequest.parse(second)
        assert claude_request.tool_results
        upstream.respond(second, anthropic_sse.message_stream([anthropic_sse.Text("TOOL_DONE")], model=case.model))
    else:
        upstream.respond(
            first,
            responses_sse.response_stream(
                [responses_sse.FunctionCall("call_test", "exec_command", {"cmd": "printf TOOL_RESULT"})],
                model=case.model,
            ),
        )
        second = await _next_request(upstream)
        codex_request = ResponsesRequest.parse(second)
        assert codex_request.function_call_outputs
        upstream.respond(second, responses_sse.response_stream([responses_sse.Message("TOOL_DONE")], model=case.model))
    observations = await task
    assert _events(observations, "tool_call_started")
    assert _events(observations, "tool_call_completed")
    assert _events(observations, "turn_completed")[-1].turn_completed.status == protocol_pb2.TURN_STATUS_COMPLETED
    upstream.assert_quiescent()


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_shared_client_reports_provider_specific_active_input_disposition(
    provider: str, cases: dict[str, Case], upstream: ScriptedUpstream, tmp_path: Path
) -> None:
    case = cases[provider]
    runner, port = await serve_runner(_runner_config(case, upstream, tmp_path))
    second_input_observed = asyncio.Event()
    tool_started = asyncio.Event()
    terminal = asyncio.Event()
    observations: list[Any] = []

    async def source() -> AsyncIterator[Any]:
        yield protocol_pb2.ClientMessage(
            start=protocol_pb2.Start(
                provider=case.provider_enum,
                cwd=str(tmp_path),
                model=case.model,
                reasoning_effort="low",
                llm_endpoint=upstream.origin,
            )
        )
        yield _input("input-1", "Run a tool, then wait for a follow-up.")
        await tool_started.wait()
        mode = protocol_pb2.INPUT_MODE_SUBMIT if provider == "claude" else protocol_pb2.INPUT_MODE_STEER
        yield _input("input-2", "Reply with ACTIVE_INPUT_OK.", mode=mode)
        await second_input_observed.wait()
        await terminal.wait()
        yield protocol_pb2.ClientMessage(close=protocol_pb2.Close(reason="test complete"))

    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    response_task: asyncio.Task[None] | None = None
    try:
        rpc = channel.stream_stream(
            "/ducktape.agentplane.v1.HarnessRunner/Connect",
            request_serializer=protocol_pb2.ClientMessage.SerializeToString,
            response_deserializer=protocol_pb2.ServerMessage.FromString,
        )
        call = rpc(source())

        async def consume() -> None:
            async for response in call:
                if response.HasField("protocol_error"):
                    raise AssertionError(response.protocol_error)
                if not response.HasField("event"):
                    continue
                event = response.event
                observations.append(event)
                kind = event.WhichOneof("observation")
                if kind == "tool_call_started":
                    tool_started.set()
                elif kind == "user_input" and event.user_input.input_id == "input-2":
                    second_input_observed.set()
                elif kind == "turn_completed":
                    terminal.set()

        response_task = asyncio.create_task(consume())
        first = await _next_request(upstream)
        if provider == "claude":
            upstream.respond(
                first,
                anthropic_sse.message_stream(
                    [anthropic_sse.ToolUse("toolu_active", "Bash", {"command": "sleep 3; printf TOOL_RESULT"})],
                    model=case.model,
                ),
            )
            second = await _next_request(upstream)
            assert MessagesRequest.parse(second).texts("user")[-1] == "Reply with ACTIVE_INPUT_OK."
            upstream.respond(
                second, anthropic_sse.message_stream([anthropic_sse.Text("ACTIVE_INPUT_OK")], model=case.model)
            )
            expected = protocol_pb2.INPUT_DISPOSITION_QUEUED
        else:
            upstream.respond(
                first,
                responses_sse.response_stream(
                    [responses_sse.FunctionCall("call_active", "exec_command", {"cmd": "sleep 3; printf TOOL_RESULT"})],
                    model=case.model,
                ),
            )
            second = await _next_request(upstream)
            assert ResponsesRequest.parse(second).messages("user")[-1].text == "Reply with ACTIVE_INPUT_OK."
            upstream.respond(
                second, responses_sse.response_stream([responses_sse.Message("ACTIVE_INPUT_OK")], model=case.model)
            )
            expected = protocol_pb2.INPUT_DISPOSITION_STEERED
        await response_task
    finally:
        if response_task is not None and not response_task.done():
            response_task.cancel()
            with suppress(asyncio.CancelledError):
                await response_task
        await channel.close()
        await runner.stop(0)
    assert _events(observations, "input_accepted")[-1].input_accepted.disposition == expected
    assert _events(observations, "turn_completed")[-1].turn_completed.status == protocol_pb2.TURN_STATUS_COMPLETED
    upstream.assert_quiescent()


@pytest.mark.parametrize("provider", ["claude", "codex"])
async def test_shared_client_admits_interrupt_and_reports_terminal_state(
    provider: str, cases: dict[str, Case], upstream: ScriptedUpstream, tmp_path: Path
) -> None:
    case = cases[provider]
    runner, port = await serve_runner(_runner_config(case, upstream, tmp_path))
    endpoint = upstream.origin
    active = asyncio.Event()
    terminal = asyncio.Event()
    observations: list[Any] = []

    async def source() -> AsyncIterator[Any]:
        yield protocol_pb2.ClientMessage(
            start=protocol_pb2.Start(
                provider=case.provider_enum,
                cwd=str(tmp_path),
                model=case.model,
                reasoning_effort="low",
                llm_endpoint=endpoint,
            )
        )
        yield _input("input-1", "Wait for the current work; do not answer early.")
        await active.wait()
        await asyncio.to_thread(upstream.next_request)
        yield protocol_pb2.ClientMessage(interrupt=protocol_pb2.Interrupt(command_id="interrupt-1", reason="test"))
        await terminal.wait()
        yield protocol_pb2.ClientMessage(close=protocol_pb2.Close(reason="test complete"))

    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        rpc = channel.stream_stream(
            "/ducktape.agentplane.v1.HarnessRunner/Connect",
            request_serializer=protocol_pb2.ClientMessage.SerializeToString,
            response_deserializer=protocol_pb2.ServerMessage.FromString,
        )
        async for response in rpc(source()):
            if response.HasField("protocol_error"):
                raise AssertionError(response.protocol_error)
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
    assert _events(observations, "interrupt_acknowledged")[-1].interrupt_acknowledged.accepted
    assert _events(observations, "turn_completed")[-1].turn_completed.status == protocol_pb2.TURN_STATUS_INTERRUPTED
    upstream.assert_quiescent()


if __name__ == "__main__":
    pytest_bazel.main()
