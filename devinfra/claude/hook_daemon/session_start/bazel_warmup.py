"""Background Bazel server warmup for Claude Code sessions.

Starts the Bazel server by running `bazel info` so the first real command
doesn't pay the JVM startup cost.
"""

import asyncio
import logging
import shlex
from pathlib import Path

logger = logging.getLogger(__name__)

_WARMUP_TIMEOUT_SECS = 120


async def warmup_bazel_server(wrapper_path: Path, project_dir: Path, env_file: Path) -> None:
    """Warm up the Bazel server. Raises on failure."""
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
