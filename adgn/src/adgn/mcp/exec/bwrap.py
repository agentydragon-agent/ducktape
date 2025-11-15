from __future__ import annotations

import os
from pathlib import Path
from shutil import which
import sys

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec.models import BaseExecResult, ExecOutcome, TimeoutMs, render_outcome_to_result
from adgn.mcp.exec.subprocess import run_proc
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

BWRAP = os.getenv("BWRAP", "bwrap")
ALLOW_UNSHARE_NET = os.getenv("DUCK_UNSHARE_NET", "0") == "1"


async def _run_in_bwrap(cmd: list[str], timeout_s: float, cwd: Path | None, stdin_text: str | None) -> ExecOutcome:
    if sys.platform != "linux":
        raise ToolError("NOT_LINUX: bubblewrap sandbox available only on Linux")
    if which(BWRAP) is None:
        raise ToolError("BWRAP_NOT_FOUND: bubblewrap (bwrap) not found in PATH")

    cwd_val = str(cwd or Path.cwd())

    argv: list[str] = [BWRAP, "--unshare-all", "--die-with-parent"]
    if ALLOW_UNSHARE_NET:
        argv.append("--unshare-net")

    argv += [
        "--ro-bind",
        "/",
        "/",
        "--bind",
        cwd_val,
        cwd_val,
        "--chdir",
        cwd_val,
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--setenv",
        "HOME",
        "/tmp",
        "--",
        *cmd,
    ]

    # chdir handled inside bwrap; pass cwd=None to subprocess
    return await run_proc(argv, timeout_s=timeout_s, cwd=None, stdin=stdin_text)


class BwrapExecArgs(BaseModel):
    cmd: list[str]
    max_bytes: int = Field(..., description="0..100_000; applies to stdin and captures")
    cwd: Path | None = None
    timeout_ms: TimeoutMs
    stdin_text: str | None = None

    model_config = ConfigDict(extra="forbid")


def make_bwrap_exec_server(name: str = "bwrap", *, default_cwd: Path | None = None) -> NotifyingFastMCP:
    """FastMCP server exposing a bubblewrap-sandboxed exec tool (Linux only).

    - Tool name: exec(cmd, max_bytes, cwd?, timeout_ms, stdin_text?)
    """
    mcp = NotifyingFastMCP(name, instructions="Local command execution via bubblewrap (Linux)")

    @mcp.flat_model()
    async def exec(input: BwrapExecArgs) -> BaseExecResult:
        """Execute a command inside a bubblewrap sandbox (Linux only)."""
        if not input.cmd or not all(isinstance(x, str) for x in input.cmd):
            raise ToolError("INVALID_CMD: cmd must be a non-empty list[str]")
        cwd_val: Path | None = input.cwd if isinstance(input.cwd, Path) else None
        if cwd_val is None and default_cwd is not None:
            cwd_val = default_cwd

        timeout_s = max(0.001, input.timeout_ms / 1000.0)
        outcome = await _run_in_bwrap(input.cmd, timeout_s, cwd_val, input.stdin_text)
        return render_outcome_to_result(outcome, input.max_bytes)

    return mcp


async def attach_bwrap_exec(mcp: Compositor, *, name: str = "bwrap", default_cwd: Path | None = None):
    """Attach a bubblewrap exec server in-proc (Linux only)."""
    server = make_bwrap_exec_server(name=name, default_cwd=default_cwd)
    await mcp.mount_inproc(name, server)
    return server
