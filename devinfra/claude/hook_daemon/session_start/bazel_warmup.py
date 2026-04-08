"""Background Bazel server warmup for Claude Code sessions.

Starts the Bazel server by running `bazel info` so the first real command
doesn't pay the JVM startup cost. Optionally runs a heavier command
(e.g. `bazel query 'tests(//...)'`) to also populate caches.
"""

import asyncio
import logging
import shlex
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WARMUP_TIMEOUT_SECS = 120
_COMMAND_TIMEOUT_SECS = 300


async def warmup_bazel_server(wrapper_path: Path, project_dir: Path, env_file: Path) -> None:
    """Warm up the Bazel server via `bazel info`. Raises on failure."""
    logger.info("Warming up Bazel server (wrapper=%s, project=%s)", wrapper_path, project_dir)
    bazel_cmd = shlex.join([str(wrapper_path), "info"])
    shell_cmd = f"source {shlex.quote(str(env_file))} && {bazel_cmd}"
    async with asyncio.timeout(_WARMUP_TIMEOUT_SECS):
        proc = await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        _, stderr_bytes = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"bazel info exited {proc.returncode}: {stderr_bytes.decode(errors='replace').strip()}")

    logger.info("Bazel server warm")


@dataclass(frozen=True)
class BazelCommandHandle:
    """Handle to a running Bazel subprocess."""

    pid: int
    wait: Callable[[], Coroutine[Any, Any, None]]


async def start_bazel_command(
    wrapper_path: Path, project_dir: Path, env_file: Path, command: str, timeout_secs: int = _COMMAND_TIMEOUT_SECS
) -> BazelCommandHandle:
    """Start a Bazel command as a background subprocess.

    Returns a handle with the PID and an awaitable that resolves when the
    process exits (raising on non-zero exit or timeout).
    """
    bazel_cmd = shlex.join([str(wrapper_path)]) + " " + command
    shell_cmd = f"source {shlex.quote(str(env_file))} && {bazel_cmd}"
    logger.info("Starting background bazel command: %s", command)

    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", shell_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(project_dir)
    )

    async def _wait() -> None:
        async with asyncio.timeout(timeout_secs):
            _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"bazel {command} exited {proc.returncode}: {stderr_bytes.decode(errors='replace').strip()}"
            )
        logger.info("Background bazel command completed: %s", command)

    return BazelCommandHandle(pid=proc.pid, wait=_wait)
