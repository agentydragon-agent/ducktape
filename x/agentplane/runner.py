"""gRPC runner for the shared Agentplane harness protocol.

The service owns one native Claude Code or Codex child per Connect stream.  The native
child remains the agent loop; this module only supervises its pipes, translates commands,
and emits both a small common event vocabulary and the exact native JSON frame as evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any
from uuid import uuid4

import grpc

from x.agentplane.capture.providers.claude import driver as claude_driver, scenarios as claude_scenarios
from x.agentplane.capture.providers.codex import driver as codex_driver, scenarios as codex_scenarios

protocol_pb2: Any = import_module("x.agentplane.protocol_pb2")

_JSON_SEPARATORS = (",", ":")


def _json(value: Any) -> str:
    return json.dumps(value, separators=_JSON_SEPARATORS, sort_keys=True)


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _claude_default_command(binary: str, model: str, resume_id: str | None) -> Sequence[str]:
    # Claude's binary is a Node executable in the pinned image.  A caller can provide a
    # command builder when its execution environment needs the ELF-loader workaround used
    # by the replay tests; the protocol and runner do not depend on that implementation detail.
    return claude_scenarios.command(binary, model=model, resume_id=resume_id)


def _codex_default_command(binary: str, endpoint: str) -> Sequence[str]:
    return codex_scenarios.command(binary, endpoint=f"{endpoint.rstrip('/')}/v1")


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Runner-owned launch configuration; credentials never cross the gRPC protocol."""

    claude_binary: str
    codex_binary: str
    environment: Mapping[str, str] = field(default_factory=dict)
    runner_id: str = "agentplane-runner"
    claude_command_builder: Callable[[str, str, str | None], Sequence[str]] = _claude_default_command
    codex_command_builder: Callable[[str, str], Sequence[str]] = _codex_default_command


class _ProtocolSession:
    def __init__(self, config: RunnerConfig, outgoing: asyncio.Queue[protocol_pb2.ServerMessage | None]):
        self.config = config
        self.outgoing = outgoing
        self.process: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task[None] | None = None
        self.stderr_task: asyncio.Task[None] | None = None
        self.waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.sequence = 0
        self.provider = protocol_pb2.PROVIDER_UNSPECIFIED
        self.thread_id = ""
        self.active_turn_id = ""
        self.active_native_turn_id = ""
        self.pending_inputs: list[str] = []
        self.open_tool_call_id = ""
        self.turn_text = ""
        self.closed = False

    async def consume(self, requests: AsyncIterable[protocol_pb2.ClientMessage]) -> None:
        try:
            started = False
            async for request in requests:
                command = request.WhichOneof("command")
                if not started:
                    if command != "start":
                        await self._protocol_error("the first client message must be start")
                        return
                    await self.start(request.start)
                    started = True
                    continue
                if command == "input":
                    await self.input(request.input)
                elif command == "interrupt":
                    await self.interrupt(request.interrupt)
                elif command == "close":
                    await self._emit(session_closed=protocol_pb2.SessionClosed(reason=request.close.reason))
                    return
                elif command is None:
                    await self._protocol_error("client message has no command")
                else:
                    await self._protocol_error(f"unsupported client command: {command}")
        except asyncio.CancelledError:
            raise
        except Exception as error:  # the stream must report a useful failure, not hang
            await self._protocol_error(f"runner failure: {error}")
        finally:
            await self.close()
            # On client cancellation the response generator has gone away; do not block a
            # cancelled consumer trying to enqueue the normal end-of-stream sentinel.
            task = asyncio.current_task()
            if task is None or task.cancelling() == 0:
                await self.outgoing.put(None)

    async def start(self, request: protocol_pb2.Start) -> None:
        if request.provider not in (protocol_pb2.PROVIDER_CLAUDE, protocol_pb2.PROVIDER_CODEX):
            await self._protocol_error("start.provider must be CLAUDE or CODEX")
            return
        if not request.llm_endpoint:
            await self._protocol_error("start.llm_endpoint is required")
            return
        self.provider = request.provider
        await self._emit_process("PROCESS_STATUS_STARTING", "launching native harness")

        if self.provider == protocol_pb2.PROVIDER_CLAUDE:
            command = self.config.claude_command_builder(
                self.config.claude_binary, request.model, request.resume_id or None
            )
            environment = {
                **os.environ,
                **self.config.environment,
                "ANTHROPIC_BASE_URL": request.llm_endpoint,
                "ANTHROPIC_AUTH_TOKEN": self.config.environment.get("ANTHROPIC_AUTH_TOKEN", "test-key"),
            }
            self.process = await self._spawn(command, request.cwd, environment)
            initialize = claude_driver.initialize()
            await self._write(initialize)
            await self._startup_frame(
                lambda frame: (
                    frame.get("type") == "control_response"
                    and frame.get("response", {}).get("request_id") == initialize["request_id"]
                )
            )
            capabilities = ["submit", "interrupt", "idle_resume"]
            native_session_id = request.resume_id
        else:
            command = self.config.codex_command_builder(self.config.codex_binary, request.llm_endpoint)
            environment = {
                **os.environ,
                **self.config.environment,
                "OPENAI_BASE_URL": f"{request.llm_endpoint.rstrip('/')}/v1",
                "OPENAI_API_KEY": self.config.environment.get("OPENAI_API_KEY", "test-key"),
            }
            self.process = await self._spawn(command, request.cwd, environment)
            initialize = codex_driver.initialize("agentplane-initialize")
            await self._write(initialize)
            await self._startup_frame(lambda frame: frame.get("id") == initialize["id"])
            await self._write(codex_driver.initialized())
            # Codex answers thread/start asynchronously.  Start the reader before waiting
            # for that response; otherwise _write_and_wait would wait on a future that no
            # task can fulfil.
            self.reader_task = asyncio.create_task(self._read_native(), name="agentplane-native-reader")
            self.stderr_task = asyncio.create_task(self._read_stderr(), name="agentplane-native-stderr")
            if request.resume_id:
                start = codex_driver.thread_resume("agentplane-thread-resume", thread_id=request.resume_id)
            else:
                start = codex_driver.thread_start(
                    "agentplane-thread-start",
                    cwd=request.cwd or ".",
                    model=request.model,
                    effort=request.reasoning_effort or "low",
                    persist=request.persist,
                )
            started = await self._write_and_wait(start, lambda frame: frame.get("id") == start["id"])
            self.thread_id = self._thread_id(started)
            capabilities = ["submit", "steer", "interrupt", "idle_resume"]
            native_session_id = self.thread_id

        if self.reader_task is None:
            self.reader_task = asyncio.create_task(self._read_native(), name="agentplane-native-reader")
        if self.stderr_task is None:
            self.stderr_task = asyncio.create_task(self._read_stderr(), name="agentplane-native-stderr")
        await self._emit_process("PROCESS_STATUS_READY", "native harness initialized")
        await self._emit_ready(native_session_id or "", capabilities)

    async def input(self, request: protocol_pb2.Input) -> None:
        if self.process is None:
            await self._protocol_error("input received before the native harness was ready")
            return
        if not request.input_id or not request.text:
            await self._protocol_error("input.input_id and input.text are required")
            return
        if request.mode == protocol_pb2.INPUT_MODE_STEER and self.provider != protocol_pb2.PROVIDER_CODEX:
            await self._emit_input_accepted(
                request.input_id,
                "INPUT_DISPOSITION_REJECTED",
                detail="Claude exposes active input as a queued submit, not a native steer operation",
            )
            return

        if self.provider == protocol_pb2.PROVIDER_CLAUDE:
            disposition = "INPUT_DISPOSITION_QUEUED" if self.active_turn_id else "INPUT_DISPOSITION_STARTED"
            if not self.active_turn_id:
                self.active_turn_id = f"turn-{uuid4().hex}"
                await self._emit_turn_started(self.active_turn_id, "")
            self.pending_inputs.append(request.input_id)
            native = claude_driver.user_frame(request.text)
            await self._write(native)
            await self._emit_input_accepted(request.input_id, disposition, native_id=native["uuid"])
            return

        self.pending_inputs.append(request.input_id)
        self.active_turn_id = f"turn-{uuid4().hex}"
        if request.mode == protocol_pb2.INPUT_MODE_STEER:
            native = codex_driver.steer(
                f"agentplane-{uuid4().hex}",
                thread_id=self.thread_id,
                turn_id=self.active_native_turn_id,
                text=request.text,
            )
            await self._write_and_wait(native, lambda frame: frame.get("id") == native["id"])
            await self._emit_input_accepted(
                request.input_id, "INPUT_DISPOSITION_STEERED", native_id=self.active_native_turn_id
            )
            return

        native = codex_driver.turn_start(f"agentplane-{uuid4().hex}", thread_id=self.thread_id, text=request.text)
        response = await self._write_and_wait(native, lambda frame: frame.get("id") == native["id"])
        turn = response.get("result", {}).get("turn", {})
        native_turn_id = turn.get("id") if isinstance(turn, dict) else None
        if not isinstance(native_turn_id, str):
            await self._emit_input_accepted(
                request.input_id, "INPUT_DISPOSITION_REJECTED", detail="Codex did not return a turn id"
            )
            return
        self.active_native_turn_id = native_turn_id
        await self._emit_input_accepted(request.input_id, "INPUT_DISPOSITION_STARTED", native_id=native_turn_id)
        await self._emit_turn_started(self.active_turn_id, native_turn_id)

    async def interrupt(self, request: protocol_pb2.Interrupt) -> None:
        if self.process is None or not self.active_turn_id:
            await self._protocol_error("interrupt received with no active turn")
            return
        if self.provider == protocol_pb2.PROVIDER_CLAUDE:
            native = claude_driver.interrupt(cancel_queued=request.cancel_queued)
        else:
            native = codex_driver.interrupt(
                f"agentplane-{uuid4().hex}", thread_id=self.thread_id, turn_id=self.active_native_turn_id
            )
        await self._write(native)
        await self._emit(
            interrupt_acknowledged=protocol_pb2.InterruptAcknowledged(
                command_id=request.command_id,
                accepted=True,
                native_id=str(native.get("request_id", native.get("id", ""))),
                detail="interrupt admitted by runner; native acknowledgement is preserved separately",
            )
        )

    async def _spawn(
        self, command: Sequence[str], cwd: str, environment: Mapping[str, str]
    ) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd or None,
            env=dict(environment),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _write(self, frame: Mapping[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("native process is not running")
        self.process.stdin.write((_json(frame) + "\n").encode())
        await self.process.stdin.drain()

    async def _write_and_wait(
        self, frame: Mapping[str, Any], predicate: Callable[[dict[str, Any]], bool]
    ) -> dict[str, Any]:
        request_id = frame.get("id")
        if not isinstance(request_id, (str, int)):
            raise ValueError("native request has no id")
        key = str(request_id)
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.waiters[key] = waiter
        try:
            await self._write(frame)
            response = await waiter
            if not predicate(response):
                raise RuntimeError(f"unexpected native response for {key}: {response!r}")
            return response
        finally:
            self.waiters.pop(key, None)

    async def _startup_frame(self, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("native process is not running")
        while line := await self.process.stdout.readline():
            frame = self._decode(line)
            await self._emit_native(frame)
            if predicate(frame):
                return frame
        raise RuntimeError("native process exited during startup")

    async def _read_native(self) -> None:
        process = self.process
        assert process is not None
        stdout = process.stdout
        assert stdout is not None
        while line := await stdout.readline():
            frame = self._decode(line)
            request_id = frame.get("id")
            if request_id is None and frame.get("type") == "control_response":
                response = frame.get("response")
                request_id = response.get("request_id") if isinstance(response, dict) else None
            if isinstance(request_id, (str, int)) and str(request_id) in self.waiters:
                waiter = self.waiters[str(request_id)]
                if not waiter.done():
                    waiter.set_result(frame)
            await self._emit_native(frame)
            await self._translate(frame)
        await self._emit_process("PROCESS_STATUS_EXITED", "native harness exited")
        error = RuntimeError("native harness exited before its pending operation completed")
        for waiter in self.waiters.values():
            if not waiter.done():
                waiter.set_exception(error)
        if self.active_turn_id:
            await self._emit_turn_completed(
                status="TURN_STATUS_PROCESS_LOST",
                result_text="",
                error=str(error),
                native_turn_id=self.active_native_turn_id,
            )

    async def _read_stderr(self) -> None:
        process = self.process
        assert process is not None
        stderr = process.stderr
        assert stderr is not None
        while chunk := await stderr.read(65536):
            # Keep stderr diagnostic in the process event without making it a second protocol.
            await self._emit_process("PROCESS_STATUS_RUNNING", chunk.decode(errors="replace"))

    @staticmethod
    def _decode(line: bytes) -> dict[str, Any]:
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("native frame is not a JSON object")
        return value

    async def _translate(self, frame: Mapping[str, Any]) -> None:
        if self.provider == protocol_pb2.PROVIDER_CLAUDE:
            await self._translate_claude(frame)
        elif self.provider == protocol_pb2.PROVIDER_CODEX:
            await self._translate_codex(frame)

    async def _translate_claude(self, frame: Mapping[str, Any]) -> None:
        frame_type = frame.get("type")
        if frame_type == "user":
            native_id = frame.get("uuid")
            if isinstance(native_id, str) and self.pending_inputs:
                input_id = self.pending_inputs.pop(0)
                await self._emit_user_input(input_id, native_id, bool(self.active_turn_id))
            message = frame.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id")
                        if isinstance(tool_id, str):
                            await self._emit(
                                tool_call_completed=protocol_pb2.ToolCallCompleted(
                                    tool_call_id=tool_id,
                                    result_json=_json(block.get("content", "")),
                                    succeeded=not bool(block.get("is_error", False)),
                                )
                            )
        elif frame_type == "stream_event":
            event = frame.get("event")
            if isinstance(event, dict):
                delta = event.get("delta")
                text = delta.get("text") if isinstance(delta, dict) else None
                if isinstance(text, str) and text:
                    await self._emit_text(text, bool(event.get("type") == "thinking_delta"), "")
        elif frame_type == "assistant":
            message = frame.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text" and isinstance(block.get("text"), str):
                            await self._emit_text(block["text"], False, "")
                        elif block.get("type") == "tool_use":
                            tool_id = block.get("id")
                            tool_name = block.get("name")
                            if isinstance(tool_id, str) and isinstance(tool_name, str):
                                self.open_tool_call_id = tool_id
                                await self._emit(
                                    tool_call_started=protocol_pb2.ToolCallStarted(
                                        tool_call_id=tool_id,
                                        native_item_id=tool_id,
                                        tool_name=tool_name,
                                        arguments_json=_json(block.get("input", {})),
                                    )
                                )
        elif frame_type == "result":
            if frame.get("terminal_reason") == "aborted_streaming":
                status = "TURN_STATUS_INTERRUPTED"
            else:
                status = "TURN_STATUS_FAILED" if frame.get("is_error") else "TURN_STATUS_COMPLETED"
            result_text = _string(frame.get("result"))
            await self._emit_turn_completed(
                status=status,
                result_text=result_text,
                error=result_text if status == "TURN_STATUS_FAILED" else "",
                native_turn_id="",
            )

    async def _translate_codex(self, frame: Mapping[str, Any]) -> None:
        method = frame.get("method")
        params = frame.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        if method == "item/started":
            item = params.get("item")
            if isinstance(item, dict) and item.get("type") == "userMessage" and self.pending_inputs:
                input_id = self.pending_inputs.pop(0)
                native_id = _string(item.get("id"))
                await self._emit_user_input(input_id, native_id, True)
            elif isinstance(item, dict) and item.get("type") in ("commandExecution", "mcpToolCall"):
                tool_id = _string(item.get("id"))
                self.open_tool_call_id = tool_id
                await self._emit(
                    tool_call_started=protocol_pb2.ToolCallStarted(
                        tool_call_id=tool_id,
                        native_item_id=tool_id,
                        tool_name=str(item.get("type")),
                        arguments_json=_json({key: value for key, value in item.items() if key not in ("id", "type")}),
                    )
                )
            return
        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if isinstance(delta, str):
                await self._emit_text(delta, False, _string(params.get("itemId", "")))
            return
        if method == "item/reasoning/summaryTextDelta":
            delta = params.get("delta")
            if isinstance(delta, str):
                await self._emit_text(delta, True, _string(params.get("itemId", "")))
            return
        if method == "item/commandExecution/outputDelta":
            delta = params.get("delta")
            if isinstance(delta, str):
                await self._emit_tool_delta(delta)
            return
        if method == "item/completed":
            item = params.get("item")
            if isinstance(item, dict) and item.get("type") in ("commandExecution", "mcpToolCall"):
                tool_id = _string(item.get("id")) or self.open_tool_call_id
                await self._emit(
                    tool_call_completed=protocol_pb2.ToolCallCompleted(
                        tool_call_id=tool_id,
                        result_json=_json(item),
                        succeeded=item.get("status") not in ("failed", "error"),
                    )
                )
                self.open_tool_call_id = ""
            return
        if method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict):
                return
            native_status = turn.get("status")
            status = {
                "completed": "TURN_STATUS_COMPLETED",
                "interrupted": "TURN_STATUS_INTERRUPTED",
                "failed": "TURN_STATUS_FAILED",
            }.get(_string(native_status), "TURN_STATUS_FAILED")
            error_value = turn.get("error", {}).get("message", "") if isinstance(turn.get("error"), dict) else ""
            error = _string(error_value)
            await self._emit_turn_completed(
                status=status, result_text="", error=error, native_turn_id=_string(turn.get("id", ""))
            )

    async def _emit_native(self, frame: Mapping[str, Any]) -> None:
        native = protocol_pb2.NativeEvent(
            provider=self.provider,
            kind=str(frame.get("type", frame.get("method", "unknown"))),
            native_id=str(frame.get("uuid", frame.get("id", ""))),
            payload_json=_json(dict(frame)),
        )
        await self._emit(native=native)

    async def _emit_ready(self, native_session_id: str, capabilities: Sequence[str]) -> None:
        await self._emit(
            ready=protocol_pb2.Ready(
                runner_id=self.config.runner_id,
                provider=self.provider,
                native_session_id=native_session_id,
                capabilities=list(capabilities),
            )
        )

    async def _emit_process(self, status: str, detail: str) -> None:
        await self._emit(process=protocol_pb2.ProcessState(status=status, detail=detail))

    async def _emit_input_accepted(
        self, input_id: str, disposition: str, native_id: str = "", detail: str = ""
    ) -> None:
        await self._emit(
            input_accepted=protocol_pb2.InputAccepted(
                input_id=input_id, disposition=disposition, native_id=native_id, detail=detail
            )
        )

    async def _emit_user_input(self, input_id: str, native_id: str, current_turn: bool) -> None:
        await self._emit(
            user_input=protocol_pb2.UserInputObserved(input_id=input_id, native_id=native_id, current_turn=current_turn)
        )

    async def _emit_turn_started(self, turn_id: str, native_turn_id: str) -> None:
        await self._emit(turn_started=protocol_pb2.TurnStarted(turn_id=turn_id, native_turn_id=native_turn_id))

    async def _emit_text(self, text: str, reasoning: bool, native_item_id: str) -> None:
        if not reasoning:
            self.turn_text += text
        await self._emit(
            text_delta=protocol_pb2.TextDelta(text=text, reasoning=reasoning, native_item_id=native_item_id)
        )

    async def _emit_tool_delta(self, text: str) -> None:
        await self._emit(tool_call_delta=protocol_pb2.ToolCallDelta(tool_call_id=self.open_tool_call_id, text=text))

    async def _emit_turn_completed(self, *, status: str, result_text: str, error: str, native_turn_id: str) -> None:
        if not result_text:
            result_text = self.turn_text
        await self._emit(
            turn_completed=protocol_pb2.TurnCompleted(
                turn_id=self.active_turn_id,
                status=status,
                result_text=result_text,
                error=error,
                native_turn_id=native_turn_id,
            )
        )
        self.active_turn_id = ""
        self.active_native_turn_id = ""
        self.turn_text = ""

    async def _protocol_error(self, message: str) -> None:
        await self.outgoing.put(protocol_pb2.ServerMessage(protocol_error=message))

    async def _emit(self, **kwargs: Any) -> None:
        self.sequence += 1
        event = protocol_pb2.Event(sequence=self.sequence)
        field, value = next(iter(kwargs.items()))
        getattr(event, field).CopyFrom(value)
        await self.outgoing.put(protocol_pb2.ServerMessage(event=event))

    @staticmethod
    def _thread_id(response: Mapping[str, Any]) -> str:
        result = response.get("result")
        thread = result.get("thread") if isinstance(result, dict) else None
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str):
            raise ValueError("Codex thread response did not contain a thread id")
        return thread_id

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for task in (self.reader_task, self.stderr_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        if self.process is not None and self.process.returncode is None:
            if self.process.stdin is not None:
                self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.terminate()
                await self.process.wait()


class HarnessRunner:
    """Generic gRPC service registration without generated gRPC stubs."""

    SERVICE = "ducktape.agentplane.v1.HarnessRunner"

    def __init__(self, config: RunnerConfig):
        self.config = config

    async def connect(
        self, requests: AsyncIterable[protocol_pb2.ClientMessage], context: grpc.aio.ServicerContext
    ) -> AsyncIterable[protocol_pb2.ServerMessage]:
        del context
        # Native readers and translations stop here when a slow client fills the queue;
        # gRPC's own flow control then propagates back to the client instead of dropping
        # deltas or native evidence.
        outgoing: asyncio.Queue[protocol_pb2.ServerMessage | None] = asyncio.Queue(maxsize=256)
        session = _ProtocolSession(self.config, outgoing)
        consumer = asyncio.create_task(session.consume(requests), name="agentplane-client-consumer")
        try:
            while message := await outgoing.get():
                yield message
        finally:
            if not consumer.done():
                consumer.cancel()
            await session.close()


def add_harness_runner_to_server(service: HarnessRunner, server: grpc.aio.Server) -> None:
    handler = grpc.stream_stream_rpc_method_handler(
        service.connect,
        request_deserializer=protocol_pb2.ClientMessage.FromString,
        response_serializer=protocol_pb2.ServerMessage.SerializeToString,
    )
    server.add_generic_rpc_handlers(
        (grpc.method_handlers_generic_handler(HarnessRunner.SERVICE, {"Connect": handler}),)
    )


async def serve(config: RunnerConfig, port: int = 0) -> tuple[grpc.aio.Server, int]:
    """Start a server and return it with its bound port; useful for tests and embedding."""
    server = grpc.aio.server()
    add_harness_runner_to_server(HarnessRunner(config), server)
    bound = server.add_insecure_port(f"127.0.0.1:{port}")
    await server.start()
    return server, bound


if __name__ == "__main__":
    raise SystemExit("embed HarnessRunner in a process and call serve(); no implicit listener is provided")
