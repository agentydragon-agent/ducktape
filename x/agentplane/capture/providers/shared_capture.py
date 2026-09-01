"""Small direct-pipe recorder used by the two provider-specific drivers."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from x.agentplane.capture.records import TextRecord


def write_jsonl(path: Path, value: BaseModel) -> None:
    with path.open("ab") as output:
        output.write(value.model_dump_json().encode() + b"\n")
        output.flush()


def text(data: bytes) -> str:
    """Store capture evidence as its UTF-8 wire text, not a redundant base64 copy."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("native capture evidence must be UTF-8 text") from error


def text_record(data: bytes) -> TextRecord:
    return TextRecord(time_ns=time.monotonic_ns(), text=text(data))


class NativeCapture:
    """Capture direct stdin/stdout/stderr pipes. No PTY, facade, or lifecycle model."""

    def __init__(self, output: Path, command: list[str], *, cwd: Path, environment: dict[str, str]):
        self.output, self.command, self.cwd, self.environment = output, command, cwd, environment
        self.process: subprocess.Popen[bytes] | None = None
        self.frames: queue.Queue[str] = queue.Queue()
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

    def write(self, frame: dict[str, Any]) -> None:
        assert self.process is not None
        assert self.process.stdin is not None
        payload = json.dumps(frame, separators=(",", ":")).encode()
        write_jsonl(self.output / "stdin.jsonl", text_record(payload))
        self.process.stdin.write(payload + b"\n")
        self.process.stdin.flush()

    def await_frame(self, predicate: Callable[[dict[str, Any]], bool], *, timeout: float) -> dict[str, Any]:
        end = time.monotonic() + timeout
        while (remaining := end - time.monotonic()) > 0:
            try:
                raw_frame = self.frames.get(timeout=remaining)
            except queue.Empty:
                break
            frame = json.loads(raw_frame)
            if not isinstance(frame, dict):
                raise ValueError("native stdout frame must be a JSON object")
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
            value = text(data)
            write_jsonl(self.output / "stdout.jsonl", TextRecord(time_ns=time.monotonic_ns(), text=value))
            self.frames.put(value)

    def _stderr(self) -> None:
        assert self.process is not None
        assert self.process.stderr is not None
        while chunk := self.process.stderr.read1(65536):
            write_jsonl(self.output / "stderr.jsonl", text_record(chunk))
