"""Small direct-pipe recorder used by the two provider-specific drivers."""

from __future__ import annotations

import base64
import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any


def write_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("ab") as output:
        output.write(json.dumps(value, separators=(",", ":")).encode() + b"\n")
        output.flush()


def raw(data: bytes) -> dict[str, Any]:
    value: dict[str, Any] = {"time_ns": time.monotonic_ns(), "base64": base64.b64encode(data).decode()}
    with suppress(UnicodeDecodeError, json.JSONDecodeError):
        value["json"] = json.loads(data)
    return value


class NativeCapture:
    """Capture direct stdin/stdout/stderr pipes. No PTY, facade, or lifecycle model."""

    def __init__(self, output: Path, command: list[str], *, cwd: Path, environment: dict[str, str]):
        self.output, self.command, self.cwd, self.environment = output, command, cwd, environment
        self.process: subprocess.Popen[bytes] | None = None
        self.frames: queue.Queue[dict[str, Any]] = queue.Queue()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        self.process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=self.environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self.threads = [
            threading.Thread(target=self._stdout, daemon=True),
            threading.Thread(target=self._stderr, daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def write(self, frame: dict[str, Any], *, action: str) -> None:
        assert self.process is not None
        assert self.process.stdin is not None
        payload = json.dumps(frame, separators=(",", ":")).encode()
        write_jsonl(self.output / "actions.jsonl", {"action": action, "frame": frame, "time_ns": time.monotonic_ns()})
        write_jsonl(self.output / "stdin.jsonl", raw(payload))
        self.process.stdin.write(payload + b"\n")
        self.process.stdin.flush()

    def await_frame(self, predicate: Callable[[dict[str, Any]], bool], *, timeout: float) -> dict[str, Any]:
        end = time.monotonic() + timeout
        while (remaining := end - time.monotonic()) > 0:
            try:
                frame = self.frames.get(timeout=remaining)
            except queue.Empty:
                break
            if predicate(frame):
                return frame
        raise TimeoutError("expected native frame was not observed")

    def close(self) -> int | None:
        if self.process is None:
            return None
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            result = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            result = self.process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=5)
        return result

    def _stdout(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        for line in self.process.stdout:
            data = line.rstrip(b"\r\n")
            write_jsonl(self.output / "stdout.jsonl", raw(data))
            try:
                parsed = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                self.frames.put(parsed)

    def _stderr(self) -> None:
        assert self.process is not None
        assert self.process.stderr is not None
        while chunk := self.process.stderr.read1(65536):
            write_jsonl(self.output / "stderr.jsonl", raw(chunk))
