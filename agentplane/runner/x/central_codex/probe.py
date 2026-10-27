"""Experimental central app-server and opaque, recording executor relay."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from aiohttp import ClientConnectorError, ClientSession, WSMsgType, web
from pydantic import BaseModel

from agentplane.native.codex import driver, scenarios
from agentplane.native.codex.testing.model import EFFORT, MODEL
from agentplane.native.codex.testing.responses import OpenAIResponses
from agentplane.native.testing.async_process import AsyncNativeProcess
from util.net import async_wait_for_port, listen_tcp, reserve_free_port


class Request(BaseModel):
    id: str
    method: str
    params: dict[str, Any]


async def rpc(process: AsyncNativeProcess, method: str, **params: Any) -> dict[str, Any]:
    request = Request(id=str(uuid4()), method=method, params=params)
    receipt = await process.request(request, matches=lambda frame: frame.get("id") == request.id)
    if "error" in receipt.frame:
        raise RuntimeError(receipt.frame)
    result = receipt.frame["result"]
    assert isinstance(result, dict)
    return result


@dataclass
class Relay:
    upstream: str
    journal: Path
    methods: list[str] = field(default_factory=list)
    effect_observed: asyncio.Event = field(default_factory=asyncio.Event)

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        downstream = web.WebSocketResponse(max_msg_size=16 * 1024 * 1024)
        async with ClientSession() as client, AsyncExitStack() as stack:
            try:
                upstream = await stack.enter_async_context(
                    client.ws_connect(self.upstream, max_msg_size=16 * 1024 * 1024)
                )
            except ClientConnectorError as error:
                with self.journal.open("a") as output:
                    output.write(json.dumps({"direction": "connect_error", "error": str(error)}) + "\n")
                raise web.HTTPServiceUnavailable(text="executor unavailable") from error
            await downstream.prepare(request)

            async def forward(source: Any, destination: Any, direction: str) -> None:
                async for message in source:
                    if message.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                        break
                    # Observe only: forward the original bytes without RPC reconstruction or replay.
                    frame = json.loads(message.data)
                    with self.journal.open("a") as output:
                        output.write(json.dumps({"direction": direction, "frame": frame}) + "\n")
                    method = frame.get("method")
                    if direction == "request" and method is not None:
                        self.methods.append(method)
                    if method == "process/output":
                        chunk = base64.b64decode(frame["params"]["chunk"])
                        if b"EFFECT_COMMITTED" in chunk:
                            self.effect_observed.set()
                    if message.type is WSMsgType.TEXT:
                        await destination.send_str(message.data)
                    else:
                        await destination.send_bytes(message.data)

            tasks = [
                asyncio.create_task(forward(downstream, upstream, "request")),
                asyncio.create_task(forward(upstream, downstream, "response")),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
            finally:
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    with suppress(asyncio.CancelledError):
                        await task
                await downstream.close()
        return downstream


@asynccontextmanager
async def relay(upstream: str, journal: Path) -> AsyncIterator[tuple[Relay, str]]:
    recorder = Relay(upstream=upstream, journal=journal)
    app = web.Application()
    app.router.add_get("/executor", recorder.handle)
    async with AsyncExitStack() as stack:
        runner = web.AppRunner(app, handler_cancellation=True)
        stack.push_async_callback(runner.cleanup)
        await runner.setup()
        with listen_tcp() as listener:
            site = web.SockSite(runner, listener.socket.dup())
            await site.start()
            yield recorder, f"ws://{listener.host}:{listener.port}/executor"


@asynccontextmanager
async def executor(
    binary: str, workspace: Path, logs: Path, environment: dict[str, str]
) -> AsyncIterator[tuple[asyncio.subprocess.Process, str]]:
    port = reserve_free_port()
    endpoint = f"ws://127.0.0.1:{port}"
    with (logs / "executor.log").open("wb") as output:
        process = await asyncio.create_subprocess_exec(
            binary,
            "exec-server",
            "--listen",
            endpoint,
            cwd=workspace,
            env=environment,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
        try:
            await async_wait_for_port("127.0.0.1", port)
            yield process, endpoint
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
            # The loss test parks a shell in a builtin read. This fixture has no cgroup fence;
            # explicitly reap that known shell, without claiming to fence arbitrary descendants.
            pid_file = workspace / "effect.pid"
            if pid_file.exists():
                with suppress(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)


@asynccontextmanager
async def sampler(
    binary: str, root: Path, evidence: Path, endpoint: OpenAIResponses, executor_url: str, incarnation: str
) -> AsyncIterator[AsyncNativeProcess]:
    logs = evidence / incarnation
    logs.mkdir()
    for name in ("stdin.jsonl", "stdout.jsonl", "stderr.jsonl"):
        (logs / name).touch()
    home = root / "codex-home"
    home.mkdir(exist_ok=True)
    url = f"{endpoint.origin}/v1"
    async with AsyncNativeProcess(
        logs,
        [
            binary,
            "-c",
            f'model_providers.agentplane.model_catalog_url="{endpoint.origin}/agentplane/codex/models"',
            *scenarios.command(binary, endpoint=url, max_retries=0)[1:],
        ],
        cwd=root,
        environment={
            "HOME": str(root),
            "PATH": os.environ["PATH"],
            "NO_PROXY": "127.0.0.1,localhost",
            # Suppresses the local environment even if a selected remote executor fails.
            "CODEX_EXEC_SERVER_URL": executor_url,
            **scenarios.environment(endpoint=url, token="sampler-only-test-key", codex_home=str(home)),
        },
    ) as process:
        await rpc(
            process,
            "initialize",
            clientInfo={"name": "central-spike", "version": "0.1"},
            capabilities={"experimentalApi": True},
        )
        await process.send(driver.initialized())
        await rpc(
            process, "environment/add", environmentId="remote-test", execServerUrl=executor_url, connectTimeoutMs=1000
        )
        yield process


async def start_thread(process: AsyncNativeProcess, workspace: Path) -> str:
    result = await rpc(
        process,
        "thread/start",
        cwd=str(workspace),
        model=MODEL,
        approvalPolicy="never",
        sandbox="danger-full-access",
        ephemeral=False,
        baseInstructions=scenarios.BASE_INSTRUCTIONS,
        config={"model_reasoning_effort": EFFORT, "features.view_image": True},
        environments=[{"environmentId": "remote-test", "cwd": str(workspace)}],
    )
    return str(result["thread"]["id"])


async def start_turn(process: AsyncNativeProcess, thread_id: str, text: str) -> str:
    result = await rpc(process, "turn/start", threadId=thread_id, input=[{"type": "text", "text": text}])
    return str(result["turn"]["id"])


class LossReceipt(BaseModel):
    thread_id: str
    turn_id: str
    tool_call_id: str
    environment_id: str
    effects: Literal["unknown"]
    observed_status: Literal["disconnected"]


async def stop_for_executor_loss(
    process: AsyncNativeProcess, *, thread_id: str, turn_id: str, tool_call_id: str, environment_id: str, journal: Path
) -> LossReceipt:
    """Experimental host policy: record uncertainty before interrupting a disconnected turn."""
    status = await rpc(process, "environment/status", environmentId=environment_id)
    receipt = LossReceipt(
        thread_id=thread_id,
        turn_id=turn_id,
        tool_call_id=tool_call_id,
        environment_id=environment_id,
        effects="unknown",
        observed_status=status["status"],
    )
    await asyncio.to_thread(journal.write_text, receipt.model_dump_json(indent=2) + "\n")
    await rpc(process, "turn/interrupt", threadId=thread_id, turnId=turn_id)
    return receipt
