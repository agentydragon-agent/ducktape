"""Native-child-only process-group lifecycle, with no PTY or terminal scraping."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class NativeProcess:
    process: subprocess.Popen[bytes]
    process_group: int

    @classmethod
    def start(cls, command: list[str], *, cwd: Path, environment: Mapping[str, str]) -> NativeProcess:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        return cls(process=process, process_group=os.getpgid(process.pid))

    def signal_group(self, signal_number: int) -> None:
        os.killpg(self.process_group, signal_number)

    def terminate(self) -> None:
        self.signal_group(signal.SIGTERM)

    def kill(self) -> None:
        self.signal_group(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)
