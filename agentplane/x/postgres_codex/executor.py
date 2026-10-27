"""Small adapter to the real upstream exec-server; never retries a request."""

import base64
from pathlib import Path
from typing import Any
from uuid import uuid4

from aiohttp import ClientWebSocketResponse, WSMsgType


class Executor:
    def __init__(self, socket: ClientWebSocketResponse, *, cwd: Path, codex_path: str):
        self.socket = socket
        self.cwd = cwd
        self.codex_path = codex_path

    async def rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid4())
        await self.socket.send_json({"id": request_id, "method": method, "params": params})
        while True:
            message = await self.socket.receive()
            if message.type != WSMsgType.TEXT:
                raise ConnectionError(f"exec-server reply lost for {method}; remote effects may have occurred")
            reply = message.json()
            if "id" in reply:
                break
            # process/read owns output collection; these push hints carry the same retained events.
            if reply.get("method") not in {"process/output", "process/exited", "process/closed"}:
                raise ValueError(f"unexpected exec-server notification: {reply}")
        if reply.get("id") != request_id or "error" in reply:
            raise RuntimeError(f"exec-server rejected {method}: {reply}")
        result: dict[str, Any] = reply["result"]
        return result

    async def initialize(self) -> None:
        await self.rpc("initialize", {"clientName": "postgres-codex-spike"})
        await self.socket.send_json({"method": "initialized", "params": {}})

    async def invoke(self, name: str, arguments: Any) -> dict[str, Any]:
        if name == "exec_command":
            if not isinstance(arguments, dict) or set(arguments) - {"cmd", "workdir"}:
                raise ValueError("spike exec_command accepts only cmd and workdir")
            argv = ["/bin/sh", "-c", arguments["cmd"]]
            cwd = Path(arguments.get("workdir", self.cwd))
        elif name == "apply_patch":
            if not isinstance(arguments, str):
                raise ValueError("apply_patch takes a patch string")
            argv = [self.codex_path, "--codex-run-as-apply-patch", arguments]
            cwd = self.cwd
        else:
            raise ValueError(f"unsupported nested tool: {name}")
        process_id = str(uuid4())
        await self.rpc(
            "process/start",
            {
                "processId": process_id,
                "argv": argv,
                "cwd": cwd.as_uri(),
                "env": {},
                "tty": False,
                "pipeStdin": False,
                "arg0": None,
            },
        )
        output = bytearray()
        after_seq = None
        while True:
            result = await self.rpc(
                "process/read", {"processId": process_id, "afterSeq": after_seq, "maxBytes": 65536, "waitMs": 1000}
            )
            for chunk in result["chunks"]:
                output.extend(base64.b64decode(chunk["chunk"]))
            after_seq = result["nextSeq"] - 1
            if result["failure"] is not None:
                raise RuntimeError(result["failure"])
            if result["closed"] and not result["exited"]:
                raise ConnectionError("remote process closed without an exit result")
            if len(output) > 1024 * 1024:
                raise ValueError("spike output exceeds 1 MiB; cell outcome remains unknown")
            if result["exited"] and not result["chunks"]:
                return {"output": output.decode(errors="replace"), "exit_code": result["exitCode"]}
