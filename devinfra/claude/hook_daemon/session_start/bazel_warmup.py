"""Background Bazel commands for Claude Code sessions."""

import asyncio
import logging
import shlex
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devinfra.claude.shell import start_with_env_file

logger = logging.getLogger(__name__)

_COMMAND_TIMEOUT_SECS = 300


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
    logger.info("Starting background bazel command: %s", command)

    proc = await start_with_env_file(bazel_cmd, env_file, cwd=project_dir)

    async def _wait() -> None:
        async with asyncio.timeout(timeout_secs):
            _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"bazel {command} exited {proc.returncode}: {stderr_bytes.decode(errors='replace').strip()}"
            )
        logger.info("Background bazel command completed: %s", command)

    return BazelCommandHandle(pid=proc.pid, wait=_wait)
