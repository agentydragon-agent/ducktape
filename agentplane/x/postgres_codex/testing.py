"""Fault injection at the remote executor boundary, forwarding to the real binary."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from aiohttp import ClientSession, web

from agentplane.x.postgres_codex.executor import Executor


class ObservingExecutor(Executor):
    """Observe a real process's first output without replacing execution."""

    def observe_output(self, event: asyncio.Event) -> None:
        self.output = event

    async def rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        result = await super().rpc(method, params)
        if method == "process/read" and result["chunks"]:
            self.output.set()
        return result


@dataclass(frozen=True)
class ExecutorServer:
    url: str
    process: asyncio.subprocess.Process


@asynccontextmanager
async def drop_completed_process_reply(executor_url: str) -> AsyncIterator[tuple[str, asyncio.Event]]:
    dropped = asyncio.Event()

    async def proxy(request: web.Request) -> web.WebSocketResponse:
        client = web.WebSocketResponse()
        await client.prepare(request)
        async with ClientSession() as http, http.ws_connect(executor_url) as upstream:
            async for message in client:
                payload = json.loads(message.data)
                await upstream.send_json(payload)
                if "id" not in payload:
                    continue
                while True:
                    reply = await upstream.receive_json()
                    if "id" in reply:
                        break
                    await client.send_json(reply)
                if payload["method"] == "process/read" and reply["result"]["exited"]:
                    dropped.set()
                    await client.close()
                    return client
                await client.send_json(reply)
        return client

    app = web.Application()
    app.router.add_get("/", proxy)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        host, port = cast(tuple[str, int], runner.addresses[0])
        yield f"ws://{host}:{port}", dropped
    finally:
        await runner.cleanup()
