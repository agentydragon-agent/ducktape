from __future__ import annotations

from pathlib import Path
import subprocess

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from adgn.mcp.compositor.server import Compositor
from adgn.mcp.exec_common.io_limits import (
    TimeoutMs,
    clamp_stdin_bytes,
    validate_max_bytes,
)
from adgn.mcp.exec_common.models import StreamOut
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP


def _emit_stream(out_b: bytes, limit: int) -> str | StreamOut:
    total = len(out_b)
    if total <= limit:
        return out_b.decode("utf-8", errors="replace")
    return StreamOut(
        truncated_text=out_b[:limit].decode("utf-8", errors="replace"),
        total_bytes=total,
    )


def _run_proc(
    argv: list[str],
    timeout_s: float,
    cwd: Path | None = None,
    stdin_b: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    p = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        cwd=cwd,
    )
    try:
        out, err = p.communicate(input=(stdin_b or b""), timeout=timeout_s)
        return (p.returncode, out or b"", err or b"")
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            out, err = p.communicate(timeout=5)
        except Exception:
            out, err = b"", b""
        return (124, out or b"", (err or b"") + b"\n[TIMEOUT]")


class DirectExecArgs(BaseModel):
    cmd: list[str]
    max_bytes: int = Field(..., description="0..100_000; applies to stdin and captures")
    cwd: Path | None = None
    timeout_ms: TimeoutMs
    stdin_text: str | None = None

    model_config = ConfigDict(extra="forbid")


class DirectExecResult(BaseModel):
    exit: int
    stdout: str | StreamOut | None = None
    stderr: str | StreamOut | None = None

    model_config = ConfigDict(extra="forbid")


def make_direct_exec_server(
    name: str = "exec",
    *,
    default_cwd: Path | None = None,
) -> NotifyingFastMCP:
    """FastMCP server exposing a direct (unsandboxed) exec tool.

    - Tool name: exec(cmd, max_bytes, cwd?, timeout_ms, stdin_text?)
    """
    mcp = NotifyingFastMCP(name, instructions="Local command execution (unsandboxed)")

    @mcp.flat_model()
    def exec(input: DirectExecArgs) -> DirectExecResult:
        """Execute a command locally (no sandbox)."""
        if not input.cmd or not all(isinstance(x, str) for x in input.cmd):
            raise ToolError("INVALID_CMD: cmd must be a non-empty list[str]")
        cwd_val: Path | None = input.cwd if isinstance(input.cwd, Path) else None
        if cwd_val is None and default_cwd is not None:
            cwd_val = default_cwd

        try:
            max_b = validate_max_bytes(input.max_bytes)
        except Exception as e:
            raise ToolError(f"INVALID_MAX_BYTES: {e}") from e

        stdin_b = clamp_stdin_bytes(input.stdin_text, max_b)
        # Preserve sub-second precision derived from timeout_ms
        timeout_s = max(0.001, float(int(input.timeout_ms)) / 1000.0)

        code, out_b, err_b = _run_proc(input.cmd, timeout_s, cwd_val, stdin_b)
        return DirectExecResult(
            exit=code,
            stdout=_emit_stream(out_b, max_b) if out_b is not None else "",
            stderr=_emit_stream(err_b, max_b) if err_b is not None else "",
        )

    return mcp


async def attach_direct_exec(
    comp: Compositor,
    *,
    name: str = "exec",
    default_cwd: Path | None = None,
):
    """Attach a direct (unsandboxed) exec server in-proc."""
    server = make_direct_exec_server(name=name, default_cwd=default_cwd)
    await comp.mount_inproc(name, server)
    return server
