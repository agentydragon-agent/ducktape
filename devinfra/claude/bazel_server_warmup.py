"""Background Bazel server warmup for Claude Code sessions.

Starts the Bazel server by running `bazel info` so the first real command
doesn't pay the JVM startup cost.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_WARMUP_TIMEOUT_SECS = 120


@dataclass(frozen=True)
class BazelServerWarmup:
    """Result of a Bazel server warmup attempt."""

    server_pid: int | None = None
    output_base: Path | None = None


def _parse_info_output(stdout: str) -> BazelServerWarmup:
    """Parse `bazel info server_pid output_base` key-value output."""
    fields: dict[str, str] = {}
    for line in stdout.strip().splitlines():
        if ": " in line:
            key, _, value = line.partition(": ")
            fields[key.strip()] = value.strip()

    pid_str = fields.get("server_pid", "")
    return BazelServerWarmup(
        server_pid=int(pid_str) if pid_str.isdigit() else None,
        output_base=Path(fields["output_base"]) if "output_base" in fields else None,
    )


async def warmup_bazel_server(wrapper_path: Path, project_dir: Path, env: dict[str, str]) -> BazelServerWarmup:
    """Start the Bazel server by running `bazel info server_pid output_base`.

    Uses the bazel wrapper so --bazelrc, proxy credentials, and session env
    vars are applied. Runs as an async subprocess with a timeout.
    """
    logger.info("Warming up Bazel server (wrapper=%s, project=%s)", wrapper_path, project_dir)

    proc = await asyncio.create_subprocess_exec(
        str(wrapper_path),
        "info",
        "server_pid",
        "output_base",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(project_dir),
        env=env,
    )
    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=_WARMUP_TIMEOUT_SECS)

    if proc.returncode != 0:
        logger.warning("Bazel server warmup failed (exit=%d): %s", proc.returncode, stderr_bytes.decode().strip())
        return BazelServerWarmup()

    result = _parse_info_output(stdout_bytes.decode())
    logger.info("Bazel server warm (pid=%s, output_base=%s)", result.server_pid, result.output_base)
    return result
