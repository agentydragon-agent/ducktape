"""Bounded, sanitized capture of a real Codex app-server stdio exchange.

The utility writes only direction-labelled protocol JSONL.  It never writes stderr, the child
environment, or raw protocol messages: every record passes through ``Sanitizer`` before it reaches
disk.  Sanitization is a safety net, not commit approval; ``testdata/README.md`` requires a human
review before promoting a capture to a fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from haku.console.x.codex_app_server.protocol import Direction

_SENSITIVE_KEY = re.compile(
    r"(?:authorization|credential|password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)", re.IGNORECASE
)
_ABSOLUTE_UNIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>]+/)*[^\s\"'<>]*")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")


@dataclass(slots=True)
class Sanitizer:
    """Stable placeholders for identifiers, paths, user text, and environment values."""

    workspace: str
    prompt: str
    environment_values: tuple[str, ...]
    ids: dict[tuple[str, str], str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_process(cls, *, workspace: Path, prompt: str) -> Sanitizer:
        # Values are inspected only for replacement.  They are never logged or serialized.
        environment_values = tuple(
            sorted(
                {value for value in os.environ.values() if len(value) >= 8 and value not in {str(workspace), prompt}},
                key=len,
                reverse=True,
            )
        )
        return cls(workspace=str(workspace), prompt=prompt, environment_values=environment_values)

    def sanitize(self, value: Any, *, key: str | None = None, parent: Mapping[str, Any] | None = None) -> Any:
        if key is not None and _SENSITIVE_KEY.search(key):
            return "<REDACTED>"
        if isinstance(value, dict):
            return {
                member_key: self.sanitize(member, key=member_key, parent=value) for member_key, member in value.items()
            }
        if isinstance(value, list):
            return [self.sanitize(member, key=key, parent=parent) for member in value]
        if isinstance(value, str):
            category = self._id_category(key, parent)
            if category is not None:
                return self._placeholder(category, value)
            return self._text(value, key=key)
        return value

    def _id_category(self, key: str | None, parent: Mapping[str, Any] | None) -> str | None:
        if key in {"threadId", "parentThreadId", "forkedFromId"}:
            return "thread"
        if key == "sessionId":
            return "session"
        if key == "turnId":
            return "turn"
        if key == "itemId":
            return "item"
        if key == "processId":
            return "process"
        if key == "clientId":
            return "client-message"
        if key != "id" or parent is None:
            return None
        if isinstance(parent.get("type"), str):
            return "item"
        if "items" in parent and "itemsView" in parent:
            return "turn"
        if "sessionId" in parent and "cwd" in parent:
            return "thread"
        return None

    def _placeholder(self, category: str, value: str) -> str:
        identity = (category, value)
        if identity not in self.ids:
            number = self.counts.get(category, 0) + 1
            self.counts[category] = number
            self.ids[identity] = f"<{category.upper()}_{number}>"
        return self.ids[identity]

    def _text(self, value: str, *, key: str | None) -> str:
        if value == self.workspace or (key in {"cwd", "codexHome", "path"} and value.startswith("/")):
            return "<WORKSPACE>" if value == self.workspace or key == "cwd" else "<ABSOLUTE_PATH>"
        text = value.replace(self.prompt, "<PROMPT>").replace(self.workspace, "<WORKSPACE>")
        for environment_value in self.environment_values:
            if environment_value in text:
                text = text.replace(environment_value, "<REDACTED_ENV_VALUE>")
        text = _BEARER.sub("Bearer <REDACTED>", text)
        text = _OPENAI_KEY.sub("<REDACTED>", text)
        return _ABSOLUTE_UNIX_PATH.sub("<ABSOLUTE_PATH>", text)


@dataclass(slots=True)
class Capture:
    process: asyncio.subprocess.Process
    output: Path
    sanitizer: Sanitizer
    timeout_seconds: float
    max_messages: int
    next_seq: int = 1
    messages: int = 0

    async def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        self.process.stdin.write(encoded)
        await self.process.stdin.drain()
        self._record(Direction.CLIENT_TO_SERVER, message)

    async def receive(self) -> dict[str, Any]:
        if self.messages >= self.max_messages:
            raise RuntimeError(f"capture exceeded --max-messages={self.max_messages}")
        assert self.process.stdout is not None
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout=self.timeout_seconds)
        if not line:
            raise RuntimeError("codex app-server closed stdout before turn/completed")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("codex app-server emitted non-JSON stdout") from exc
        if not isinstance(message, dict):
            raise RuntimeError("codex app-server emitted a non-object JSON message")
        self._record(Direction.SERVER_TO_CLIENT, message)
        return message

    async def response(self, request_id: int) -> dict[str, Any]:
        while True:
            message = await self.receive()
            if message.get("id") == request_id and ("result" in message or "error" in message):
                if "error" in message:
                    raise RuntimeError(f"app-server request {request_id} failed; inspect sanitized capture")
                return message

    def _record(self, direction: Direction, message: dict[str, Any]) -> None:
        self.messages += 1
        record = {"seq": self.next_seq, "direction": direction.value, "message": self.sanitizer.sanitize(message)}
        self.next_seq += 1
        with self.output.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            stream.write("\n")


async def capture(args: argparse.Namespace) -> None:
    workspace, output = _capture_paths(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("")
    process = await asyncio.create_subprocess_exec(
        args.codex,
        "app-server",
        "--listen",
        "stdio://",
        cwd=workspace,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,
    )
    stderr_drain = asyncio.create_task(_discard_stderr(process))
    recorder = Capture(
        process=process,
        output=output,
        sanitizer=Sanitizer.from_process(workspace=workspace, prompt=args.prompt),
        timeout_seconds=args.timeout_seconds,
        max_messages=args.max_messages,
    )
    try:
        await recorder.send(
            {
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {
                        "name": "haku_codex_trace_capture",
                        "title": "Haku Codex trace capture",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": False},
                },
            }
        )
        await recorder.response(1)
        await recorder.send({"method": "initialized"})

        thread_params: dict[str, Any] = {
            "cwd": str(workspace),
            "approvalPolicy": "never",
            "sandbox": "workspaceWrite",
            "ephemeral": True,
        }
        if args.model is not None:
            thread_params["model"] = args.model
        await recorder.send({"method": "thread/start", "id": 2, "params": thread_params})
        thread_response = await recorder.response(2)
        thread_id = _nested_string(thread_response, "result", "thread", "id")

        await recorder.send(
            {
                "method": "turn/start",
                "id": 3,
                "params": {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": args.prompt, "text_elements": []}],
                },
            }
        )
        turn_response = await recorder.response(3)
        turn_id = _nested_string(turn_response, "result", "turn", "id")
        while True:
            message = await recorder.receive()
            params = message.get("params")
            if (
                message.get("method") == "turn/completed"
                and isinstance(params, dict)
                and params.get("threadId") == thread_id
                and isinstance(params.get("turn"), dict)
                and params["turn"].get("id") == turn_id
            ):
                break
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            process.terminate()
            await process.wait()
        await stderr_drain


async def _discard_stderr(process: asyncio.subprocess.Process) -> None:
    """Drain diagnostics so the child cannot block; never print or persist them."""
    assert process.stderr is not None
    while await process.stderr.readline():
        pass


def _capture_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve paths outside async code; these operations are immediate and bounded."""
    return Path(args.cwd).resolve(), Path(args.output).resolve()


def _nested_string(value: Mapping[str, Any], *path: str) -> str:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            raise RuntimeError(f"missing response field: {'.'.join(path)}")
        current = current.get(key)
    if not isinstance(current, str):
        raise RuntimeError(f"missing response field: {'.'.join(path)}")
    return current


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--codex", default="codex", help="path to pinned Codex executable")
    result.add_argument("--cwd", required=True, help="disposable workspace used by the turn")
    result.add_argument("--output", required=True, help="sanitized JSONL destination")
    result.add_argument("--prompt", required=True, help="reviewable capture prompt")
    result.add_argument("--model", help="optional model override")
    result.add_argument("--timeout-seconds", type=float, default=60.0)
    result.add_argument("--max-messages", type=int, default=2000)
    return result


def main(argv: Sequence[str] | None = None) -> None:
    asyncio.run(capture(parser().parse_args(argv)))


if __name__ == "__main__":
    main()
