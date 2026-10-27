"""Protocol V1 adapter for the pinned upstream codex-code-mode-host binary."""

import asyncio
import json
import struct
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentplane.x.postgres_codex.executor import Executor
from agentplane.x.postgres_codex.store import Owner, Store


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "exec_command",
            "tool_name": {"name": "exec_command", "namespace": None},
            "description": "Run a shell command to completion. Returns output and exit_code. This spike accepts cmd and optional absolute workdir only; no stdin, PTY or yielding.",
            "kind": "function",
            "input_schema": {
                "type": "object",
                "properties": {"cmd": {"type": "string"}, "workdir": {"type": "string"}},
                "required": ["cmd"],
                "additionalProperties": False,
            },
            "output_schema": None,
        },
        {
            "name": "apply_patch",
            "tool_name": {"name": "apply_patch", "namespace": None},
            "description": "Apply a Codex *** Begin Patch / *** End Patch patch through the remote upstream apply-patch implementation.",
            "kind": "freeform",
            "input_schema": None,
            "output_schema": None,
        },
    ]


class CodeMode:
    def __init__(self, process: asyncio.subprocess.Process, store: Store, owner: Owner, executor: Executor):
        self.process = process
        self.store = store
        self.owner = owner
        self.executor = executor
        self.session_id = str(uuid4())

    async def send(self, value: dict[str, Any]) -> None:
        data = json.dumps(value).encode()
        assert self.process.stdin is not None
        self.process.stdin.write(struct.pack("<I", len(data)) + data)
        await self.process.stdin.drain()

    async def receive(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        length = struct.unpack("<I", await self.process.stdout.readexactly(4))[0]
        if length > 64 * 1024 * 1024:
            raise ValueError("upstream code-mode frame exceeds protocol limit")
        value: dict[str, Any] = json.loads(await self.process.stdout.readexactly(length))
        return value

    async def open(self) -> None:
        await self.send(
            {
                "type": "connection/hello",
                "supportedVersions": [1],
                "requiredCapabilities": [],
                "optionalCapabilities": [],
            }
        )
        hello = await self.receive()
        if hello != {"type": "connection/ready", "selectedVersion": 1, "capabilities": []}:
            raise ValueError(f"unexpected code-mode handshake: {hello}")
        await self.send(
            {"type": "operation/request", "id": 1, "request": {"method": "session/open", "sessionId": self.session_id}}
        )
        reply = await self.receive()
        if reply["result"]["status"] != "ok":
            raise RuntimeError(reply)

    async def execute(self, call: dict[str, Any]) -> list[dict[str, Any]]:
        await self.send(
            {
                "type": "operation/request",
                "id": 2,
                "request": {
                    "method": "session/execute",
                    "sessionId": self.session_id,
                    "request": {
                        "tool_call_id": call["call_id"],
                        "source": call["input"],
                        "enabled_tools": tool_definitions(),
                        "yield_time_ms": 60000,
                        "max_output_tokens": 10000,
                    },
                },
            }
        )
        while True:
            frame = await self.receive()
            if frame["type"] == "delegate/request":
                request = frame["request"]
                if request["type"] != "tool/invoke":
                    raise ValueError("spike does not support notify")
                invocation = request["invocation"]
                intent_id = await self.store.record_nested(
                    self.owner, {"kind": "tool", "call_id": call["call_id"], **invocation}
                )
                # No transport retry: reply loss leaves both this nested intent and its outer cell unresolved.
                result = await self.executor.invoke(invocation["tool_name"]["name"], invocation["input"])
                await self.store.finish_nested(self.owner, intent_id, result)
                await self.send(
                    {
                        "type": "delegate/response",
                        "id": frame["id"],
                        "result": {"status": "ok", "value": {"type": "tool/result", "result": result}},
                    }
                )
            elif frame["type"] == "execute/initialResponse":
                result = frame["result"]
                if result["status"] != "ok":
                    raise RuntimeError(result)
                runtime = result["value"]
                if "Result" not in runtime:
                    raise ValueError("spike cannot resume yielded/terminated JS cells; outcome remains unknown")
                completed = runtime["Result"]
                items: list[dict[str, Any]] = completed["content_items"]
                if completed["error_text"] is not None:
                    items = [*items, {"type": "input_text", "text": completed["error_text"]}]
                return items
            elif frame["type"] == "operation/response":
                if frame["result"]["status"] != "ok":
                    raise RuntimeError(frame)
            elif frame["type"] != "cell/closed":
                raise ValueError(f"unexpected code-mode frame: {frame}")


@asynccontextmanager
async def code_mode(binary: str, logs: Path, store: Store, owner: Owner, executor: Executor) -> AsyncIterator[CodeMode]:
    with logs.open("ab") as stderr:
        process = await asyncio.create_subprocess_exec(
            binary, "--listen", "stdio", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr
        )
        try:
            runtime = CodeMode(process, store, owner, executor)
            await runtime.open()
            yield runtime
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
