from __future__ import annotations

import os
from pathlib import Path
from shutil import which
import subprocess
import sys

from adgn.mcp._shared.fastmcp_helpers import SafeFastMCP
from adgn.mcp._shared.fastmcp_helpers import mcp_flat_model
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from adgn.mcp.exec_common.io_limits import (
    validate_max_bytes,
    clamp_stdin_bytes,
)
from adgn.mcp.exec_common.models import StreamOut

DEFAULT_TIMEOUT_S = int(os.getenv("DUCK_TIMEOUT_S", "30"))
BWRAP = os.getenv("BWRAP", "bwrap")
ALLOW_UNSHARE_NET = os.getenv("DUCK_UNSHARE_NET", "0") == "1"
ALLOW_UNSANDBOXED = (
    os.getenv("DUCK_ALLOW_UNSANDBOXED", "0") == "1"
)  # dev override on non-Linux


def _emit_stream(out_b: bytes, limit: int) -> str | StreamOut:
    total = len(out_b)
    if total <= limit:
        # Fully captured → return plain string
        return out_b.decode("utf-8", errors="replace")
    # Truncated → return structured marker with metadata
    return StreamOut(
        text=out_b[:limit].decode("utf-8", errors="replace"),
        truncated=True,
        total_bytes=total,
    )


def _run_proc(
    argv: list[str],
    timeout_s: int,
    cwd: str | None = None,
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


def _run_in_sandbox(
    cmd: list[str],
    timeout_s: int,
    cwd: str | None,
    stdin_b: bytes | None,
) -> tuple[int, bytes, bytes]:
    # Enforce sandboxing: on non-Linux, only allow with explicit override
    if sys.platform != "linux":
        if ALLOW_UNSANDBOXED:
            return _run_proc(cmd, timeout_s=timeout_s, cwd=cwd, stdin_b=stdin_b)
        return (
            2,
            b"",
            b"sandbox unavailable on this platform; set DUCK_ALLOW_UNSANDBOXED=1 to override",
        )

    # Linux: require bubblewrap
    if which(BWRAP) is None:
        return (2, b"", b"bubblewrap (bwrap) not found in PATH")

    cwd_val = cwd or str(Path.cwd())

    argv: list[str] = [
        BWRAP,
        "--unshare-all",
        "--die-with-parent",
    ]
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
    return _run_proc(argv, timeout_s=timeout_s, cwd=None, stdin_b=stdin_b)


class LocalExecArgs(BaseModel):
    cmd: list[str]
    max_bytes: int = Field(..., description="0..100_000; applies to stdin and captures")
    cwd: str | None = None
    timeout_ms: int | None = None
    stdin_text: str | None = None

    model_config = ConfigDict(extra="forbid")


class LocalExecResult(BaseModel):
    exit: int
    stdout: str | StreamOut | None = None
    stderr: str | StreamOut | None = None

    model_config = ConfigDict(extra="forbid")


def _exec_core(payload: LocalExecArgs, *, sandbox_enabled: bool) -> LocalExecResult:
    if not payload.cmd or not all(isinstance(x, str) for x in payload.cmd):
        raise ToolError("INVALID_CMD: cmd must be a non-empty list[str]")

    to = (
        DEFAULT_TIMEOUT_S
        if not isinstance(payload.timeout_ms, int)
        else max(1, int(payload.timeout_ms / 1000))
    )
    cwd_val = payload.cwd if isinstance(payload.cwd, str) else None

    try:
        max_b = validate_max_bytes(payload.max_bytes)
    except Exception as e:
        raise ToolError(f"INVALID_MAX_BYTES: {e}") from e

    stdin_b = clamp_stdin_bytes(payload.stdin_text, max_b)

    if sandbox_enabled:
        code, out_b, err_b = _run_in_sandbox(payload.cmd, to, cwd_val, stdin_b)
    else:
        code, out_b, err_b = _run_proc(payload.cmd, to, cwd_val, stdin_b)

    return LocalExecResult(
        exit=code,
        stdout=_emit_stream(out_b, max_b) if out_b is not None else "",
        stderr=_emit_stream(err_b, max_b) if err_b is not None else "",
    )


def make_local_exec_mcp(
    name: str = "local",
    *,
    default_cwd: str | None = None,
    sandbox_enabled: bool = True,
) -> SafeFastMCP:
    """FastMCP server exposing a local exec tool.

    Tools:
      - exec(
          cmd: list[str],
          max_bytes: int,  # 0..100_000; applies to stdin write and stdout/stderr capture
          cwd: str | None = None,
          timeout_ms: int | None = None,
          stdin_text: str | None = None,
        ) -> { exit: int, stdout: str|{text,truncated,total_bytes}, stderr: str|{...} }
    """
    mcp = SafeFastMCP(name, instructions="Local command execution")

    @mcp_flat_model(
        mcp,
        name="exec",
        title="Local exec",
        description="Execute a command locally (optionally sandboxed)",
        structured_output=True,
    )
    def exec(input: LocalExecArgs) -> LocalExecResult:
        # Apply default cwd if not provided
        if input.cwd is None and default_cwd is not None:
            input = input.copy(update={"cwd": default_cwd})
        return _exec_core(input, sandbox_enabled=sandbox_enabled)

    return mcp
