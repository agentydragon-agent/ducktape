from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import sys

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec_common.io_limits import (
    StreamReadResult,
    TimeoutMs,
    clamp_stdin_bytes,
    read_stream_limited_async,
)
from adgn.mcp.exec_common.models import StreamOut
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.seatbelt.model import EnvPassthroughMode, SBPLPolicy
from adgn.seatbelt.runner import apopen, collect_unified_sandbox_denies
from docker import DockerClient

SERVER_NAME = "seatbelt_exec"


logger = logging.getLogger(__name__)


# Default env whitelist used when passing through only a safe subset.
DEFAULT_ENV_WHITELIST: tuple[str, ...] = (
    "HOME",
    "LOGNAME",
    "PATH",
    "SHELL",
    "USER",
    "USERNAME",
    "TMPDIR",
    "TEMP",
    "TMP",
)


class SandboxExecArgs(BaseModel):
    # Stateless: require a full policy on every call
    policy: SBPLPolicy
    argv: list[str] = Field(min_length=1)
    max_bytes: int = Field(
        ..., ge=0, le=100_000, description="0..100_000; applies to stdin and captures"
    )
    cwd: Path | None = None
    # Explicit env to set/override in the child (applied after policy.env passthrough base)
    env: dict[str, str] | None = None
    timeout_ms: TimeoutMs
    trace: bool = False
    stdin_text: str | None = None

    model_config = ConfigDict(extra="forbid")


class SandboxExecResult(BaseModel):
    """Exec result for sandbox_exec with optional structured streams.

    - stdout/stderr: if fully read (not truncated), a plain string is returned
      for simplicity; if truncated, a StreamOut object is returned.
    - Note: stdout/stderr are UTF-8 decoded with replacement.
    """

    exit_code: int | None
    timeout: bool
    duration_ms: int
    stdout: str | StreamOut | None = None
    stderr: str | StreamOut | None = None
    trace_text: str | None = None
    unified_sandbox_denies_text: str | None = None

    model_config = ConfigDict(extra="forbid")


class SeatbeltExecMCP(NotifyingFastMCP):
    def __init__(
        self,
        name: str = SERVER_NAME,
        *,
        agent_id: str | None = None,
        persistence=None,
        docker_client: DockerClient,
    ) -> None:
        # Refuse to instantiate on non-darwin
        if sys.platform != "darwin":
            raise RuntimeError("seatbelt_exec is macOS-only (requires sandbox-exec)")
        super().__init__(
            name,
            instructions=(
                "Execute commands via macOS seatbelt (sandbox-exec). Provide a full SBPL policy per call."
            ),
        )
        if not agent_id:
            raise ValueError("SeatbeltExecMCP requires agent_id")
        self._agent_id = agent_id
        self._SBPL = TypeAdapter(SBPLPolicy)
        self._docker = docker_client

        # Register sandbox_exec tool
        @self.flat_model()
        async def sandbox_exec(input: SandboxExecArgs) -> SandboxExecResult:  # type: ignore[unused-ignore]
            """Execute a command via macOS seatbelt (sandbox-exec). Provide a full SBPL policy per call."""
            # Platform precheck
            if sys.platform != "darwin":
                raise ToolError("NOT_DARWIN: sandbox available only on macOS")

            # Pydantic has already validated argv min length and max_bytes range
            max_b = input.max_bytes

            cwd_path = input.cwd.resolve() if isinstance(input.cwd, Path) else None

            # Stateless: require inline policy (validated by Pydantic)
            policy = input.policy

            # Prepare stdin bytes (clamped to max_bytes); no metadata returned for stdin
            stdin_b = clamp_stdin_bytes(input.stdin_text, max_b)

            # Compute child environment based on policy.env (default: whitelist with safe defaults),
            # then overlay any explicit env values provided in the request.
            env_parent = os.environ

            mode = policy.env.mode
            wl = policy.env.whitelist or list(DEFAULT_ENV_WHITELIST)
            if mode == EnvPassthroughMode.ALL:
                child_env: dict[str, str] = dict(env_parent)
            else:
                child_env = {k: v for k, v in env_parent.items() if k in wl}
            if input.env:
                child_env.update({k: str(v) for k, v in input.env.items()})

            # Run with apopen so we can enforce timeout and kill if needed
            try:
                async with await apopen(
                    input.argv,
                    policy,
                    cwd=cwd_path,
                    env=child_env,
                    trace=input.trace,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ) as proc:
                    loop = asyncio.get_event_loop()
                    start = loop.time()
                    total_secs = max(0.001, float(input.timeout_ms) / 1000.0)
                    deadline = start + total_secs

                    def _remaining() -> float:
                        return max(0.0, deadline - loop.time())

                    # Kick off reads first; then write stdin; this avoids fill/lock
                    stdout_task = asyncio.create_task(
                        read_stream_limited_async(proc.stdout, store_limit=max_b)
                    )
                    stderr_task = asyncio.create_task(
                        read_stream_limited_async(proc.stderr, store_limit=max_b)
                    )

                    # Write stdin (if any), then close to signal EOF
                    try:
                        if proc.stdin is not None:
                            if stdin_b:
                                proc.stdin.write(stdin_b)
                                await proc.stdin.drain()
                            proc.stdin.close()
                    except Exception as e:
                        # Record the failure but do not crash; exit code/streams will reflect errors
                        logger.debug("stdin write/close failed: %s", e)

                    timed_out = False
                    try:
                        # Wait for stream drains and process exit with timeout
                        # Enforce a single overall timeout budget across both awaits
                        t1 = _remaining()
                        await asyncio.wait_for(
                            asyncio.gather(stdout_task, stderr_task),
                            timeout=t1,
                        )
                        t2 = _remaining()
                        await asyncio.wait_for(
                            proc.wait(),
                            timeout=t2,
                        )
                    except asyncio.TimeoutError:
                        # Best-effort termination; __aexit__ will also ensure cleanup
                        timed_out = True
                        try:
                            proc.kill()
                        except Exception as e:
                            logger.debug("proc.kill() failed: %s", e)
                        try:
                            await proc.wait()
                        except Exception as e:
                            logger.debug("proc.wait() after kill failed: %s", e)

                    duration_ms = int(round((loop.time() - start) * 1000))

                    # Collect stream results (completed or cancelled → default empty)
                    def _done_result(t: asyncio.Task[StreamReadResult]) -> StreamReadResult:
                        if t.done() and not t.cancelled() and t.exception() is None:
                            return t.result()
                        return StreamReadResult(stored_text="", truncated=False, total_bytes=0)

                    out_res = _done_result(stdout_task)
                    err_res = _done_result(stderr_task)

                    def _emit_stream(res: StreamReadResult) -> str | StreamOut | None:
                        # If process produced zero bytes and we didn't store anything, return empty string
                        if res.total_bytes == 0:
                            return ""
                        if res.truncated:
                            return StreamOut(
                                truncated_text=res.stored_text,
                                total_bytes=res.total_bytes,
                            )
                        return res.stored_text

                    stdout_val = _emit_stream(out_res)
                    stderr_val = _emit_stream(err_res)

                    trace_text: str | None = None
                    if input.trace and proc.trace_file and proc.trace_file.exists():
                        try:
                            trace_text = proc.trace_file.read_text(errors="replace")
                        except Exception as e:
                            logger.debug("failed to read trace file: %s", e)
                            trace_text = None

                    # Disabled for now: unified sandbox denies are noisy/unscoped.
                    unified_text: str | None = None
                    if False and (not timed_out and (proc.returncode or 0) != 0):
                        try:
                            _p, unified_text = collect_unified_sandbox_denies(proc.artifacts_dir)
                        except Exception as e:
                            logger.debug("collect unified denies failed: %s", e)
                            unified_text = None

                    return SandboxExecResult(
                        exit_code=(None if timed_out else proc.returncode),
                        timeout=timed_out,
                        duration_ms=duration_ms,
                        stdout=stdout_val,
                        stderr=stderr_val,
                        trace_text=trace_text,
                        unified_sandbox_denies_text=unified_text,
                    )
            except FileNotFoundError as e:
                # sandbox-exec missing
                raise ToolError(f"SANDBOX_EXEC_MISSING: {e}") from e
            except Exception as e:
                raise ToolError(str(e)) from e

        # ---- Template management tools ----
        # No template management or resources: stateless server


async def attach_seatbelt_exec(
    comp: Compositor,
    *,
    agent_id: str,
    persistence,
    docker_client: DockerClient,
    name: str = SERVER_NAME,
):
    server = SeatbeltExecMCP(
        name,
        agent_id=agent_id,
        persistence=persistence,
        docker_client=docker_client,
    )
    await comp.mount_inproc(name, server)
    return server
