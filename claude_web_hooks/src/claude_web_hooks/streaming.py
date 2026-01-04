"""Streaming command execution with heartbeat output."""

from __future__ import annotations

import logging
import os
import select
import subprocess
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 0.5


def run_streaming(
    cmd: list[str | Path], operation: str | None = None, check: bool = True, env: dict[str, str] | None = None
) -> int:
    """Run command with real-time streaming output.

    Args:
        cmd: Command and arguments (accepts str or Path)
        operation: Description for logs (defaults to first element of cmd)
        check: Raise RuntimeError on non-zero exit
        env: Additional environment variables
    """
    cmd_strs = [str(c) for c in cmd]
    op = operation or cmd_strs[0]

    log.info("run: %s", " ".join(cmd_strs))
    start_time = datetime.now()

    merged_env = {**os.environ, **(env or {})}

    proc = subprocess.Popen(
        cmd_strs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=merged_env
    )

    assert proc.stdout is not None

    last_output_time = datetime.now()
    heartbeat_count = 0

    while True:
        ready, _, _ = select.select([proc.stdout], [], [], HEARTBEAT_INTERVAL_SECONDS)

        if ready:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.rstrip("\n\r")
            if line:
                log.info("%s", line)
                last_output_time = datetime.now()
        else:
            heartbeat_count += 1
            elapsed = (datetime.now() - start_time).total_seconds()
            silence = (datetime.now() - last_output_time).total_seconds()
            log.info("%s: still running (%.0fs elapsed, %.0fs quiet)", op, elapsed, silence)

    proc.wait()
    elapsed = (datetime.now() - start_time).total_seconds()

    if proc.returncode == 0:
        log.info("%s: done (%.1fs)", op, elapsed)
    else:
        log.error("%s: failed with code %d (%.1fs)", op, proc.returncode, elapsed)
        if check:
            raise RuntimeError(f"{op} failed with exit code {proc.returncode}")

    return proc.returncode
