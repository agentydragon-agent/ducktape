"""Exact direct-pipe capture shared by provider-specific scenario drivers only."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from x.agentplane.capture.artifacts import CaptureBundle
from x.agentplane.capture.framing import NewlineFramer
from x.agentplane.capture.process import NativeProcess
from x.agentplane.capture.records import RawRecord, json_wrapper


class NativeCapture:
    """A no-PTY native child with flush-before-interpret evidence collection."""

    def __init__(self, bundle: CaptureBundle, command: list[str], *, cwd: Path, environment: dict[str, str]):
        self.bundle = bundle
        self.command = command
        self.cwd = cwd
        self.environment = environment
        self.process: NativeProcess | None = None
        self._frames: queue.Queue[dict[str, Any]] = queue.Queue()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self.bundle.append_json("process-events.jsonl", {"event": "spawn_requested", "command": self.command})
        self.process = NativeProcess.start(self.command, cwd=self.cwd, environment=self.environment)
        self.bundle.append_json(
            "process-events.jsonl",
            {"event": "spawn_succeeded", "pid": self.process.process.pid, "process_group": self.process.process_group},
        )
        assert self.process.process.stdout is not None
        assert self.process.process.stderr is not None
        self._threads = [
            threading.Thread(target=self._read_stdout, name="native-stdout", daemon=True),
            threading.Thread(target=self._read_stderr, name="native-stderr", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def write(self, frame: dict[str, Any], *, action: str) -> None:
        if self.process is None or self.process.process.stdin is None:
            raise RuntimeError("native process is not running")
        payload = json.dumps(frame, separators=(",", ":")).encode("utf-8")
        self.bundle.append_json("scenario-actions.jsonl", {"action": action, "native_frame": frame})
        self.bundle.append_raw(
            "native-stdin.frames.jsonl", RawRecord(payload, 0, 0, "harness_stdin", 1, delimiter=b"\n")
        )
        self.process.process.stdin.write(payload + b"\n")
        self.process.process.stdin.flush()

    def await_frame(self, predicate: Callable[[dict[str, Any]], bool], *, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                item = self._frames.get(timeout=remaining)
            except queue.Empty:
                break
            if predicate(item):
                return item
        raise TimeoutError("native frame predicate was not observed")

    def close(self) -> int | None:
        if self.process is None:
            return None
        process = self.process.process
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
            self.bundle.append_json("process-events.jsonl", {"event": "stdin_closed"})
        try:
            exit_code = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.bundle.append_json("process-events.jsonl", {"event": "signal_requested", "signal": "SIGTERM"})
            self.process.terminate()
            try:
                exit_code = self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.bundle.append_json("process-events.jsonl", {"event": "signal_requested", "signal": "SIGKILL"})
                self.process.kill()
                exit_code = self.process.wait(timeout=5)
        for thread in self._threads:
            thread.join(timeout=5)
        self.bundle.append_json("process-events.jsonl", {"event": "exited", "exit_code": exit_code})
        return exit_code

    def _read_stdout(self) -> None:
        assert self.process is not None
        assert self.process.process.stdout is not None
        framer = NewlineFramer()
        while chunk := self.process.process.stdout.read1(65536):
            for data, delimiter, eof_frame in framer.feed(chunk):
                self._record_stdout(data, delimiter, eof_frame)
        for data, delimiter, eof_frame in framer.finish():
            self._record_stdout(data, delimiter, eof_frame)
        self.bundle.append_json("process-events.jsonl", {"event": "stdout_eof"})

    def _record_stdout(self, data: bytes, delimiter: bytes, eof_frame: bool) -> None:
        self.bundle.append_raw(
            "native-stdout.frames.jsonl", RawRecord(data, 0, 0, "harness_stdout", 1, delimiter, eof_frame)
        )
        parsed = json_wrapper(data)
        if parsed["state"] == "parsed" and isinstance(parsed["value"], dict):
            self._frames.put(parsed["value"])

    def _read_stderr(self) -> None:
        assert self.process is not None
        assert self.process.process.stderr is not None
        while chunk := self.process.process.stderr.read1(65536):
            self.bundle.append_raw("native-stderr.chunks.jsonl", RawRecord(chunk, 0, 0, "harness_stderr", 1))
        self.bundle.append_json("process-events.jsonl", {"event": "stderr_eof"})
