from __future__ import annotations

from typing import Any
import os
import sys
import subprocess
from pathlib import Path
from shutil import which

from mcp.server.fastmcp import FastMCP

# ---- Local exec implementation (moved from mini_codex/local_tools.py) ----
DEFAULT_TIMEOUT_S = int(os.getenv("DUCK_TIMEOUT_S", "30"))
TRUNCATE_BYTES = 8 * 1024
BWRAP = os.getenv("BWRAP", "bwrap")
ALLOW_UNSHARE_NET = os.getenv("DUCK_UNSHARE_NET", "0") == "1"
ALLOW_UNSANDBOXED = os.getenv("DUCK_ALLOW_UNSANDBOXED", "0") == "1"  # dev override on non-Linux


def _truncate_bytes(s: str, limit: int) -> str:
    data = s.encode("utf-8")
    if len(data) <= limit:
        return s
    marker = b"\n[TRUNCATED]"
    if limit <= len(marker):
        return "[TRUNCATED]"
    head = data[: limit - len(marker)]
    return head.decode("utf-8", errors="ignore") + "\n[TRUNCATED]"


def _run_proc(argv: list[str], timeout_s: int, cwd: str | None = None) -> tuple[int, str, str]:
    p = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    try:
        out, err = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return (124, _truncate_bytes(out, TRUNCATE_BYTES), _truncate_bytes(err + "\n[TIMEOUT]", TRUNCATE_BYTES))

    return (p.returncode, _truncate_bytes(out, TRUNCATE_BYTES), _truncate_bytes(err, TRUNCATE_BYTES))


def _run_in_sandbox(cmd: list[str], timeout_s: int, cwd: str | None) -> tuple[int, str, str]:
    # Enforce sandboxing: on non-Linux, only allow with explicit override
    if sys.platform != "linux":
        if ALLOW_UNSANDBOXED:
            return _run_proc(cmd, timeout_s=timeout_s, cwd=cwd)
        return (2, "", "sandbox unavailable on this platform; set DUCK_ALLOW_UNSANDBOXED=1 to override")

    # Linux: require bubblewrap
    if which(BWRAP) is None:
        return (2, "", "bubblewrap (bwrap) not found in PATH")

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
    return _run_proc(argv, timeout_s=timeout_s, cwd=None)


def exec_handler(args: dict[str, Any], *, sandbox_enabled: bool = True) -> dict[str, Any]:
    """Execute a shell command with optional cwd/timeout."""
    cmd = args.get("cmd")
    if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
        return {"exit": 2, "stdout": "", "stderr": "invalid cmd"}

    timeout_ms = args.get("timeout_ms")
    to = DEFAULT_TIMEOUT_S if not isinstance(timeout_ms, int) else max(1, int(timeout_ms / 1000))
    cwd_val = args.get("cwd") if isinstance(args.get("cwd"), str) else None

    runner = _run_in_sandbox if sandbox_enabled else _run_proc
    code, out, err = runner(cmd, timeout_s=to, cwd=cwd_val)
    return {"exit": code, "stdout": out, "stderr": err}


def make_local_exec_mcp(
    name: str = "local",
    *,
    default_cwd: str | None = None,
    sandbox_enabled: bool = True,
) -> FastMCP:
    """FastMCP server exposing a local exec tool.

    Tools:
      - exec(cmd: list[str], cwd: str | None = None, timeout_ms: int | None = None)
        → {exit:int, stdout:str, stderr:str}
    """
    mcp = FastMCP(name, instructions="Local command execution")

    @mcp.tool()
    def exec(cmd: list[str], cwd: str | None = None, timeout_ms: int | None = None) -> dict[str, Any]:  # noqa: A003
        return exec_handler(
            {"cmd": cmd, "cwd": cwd or default_cwd, "timeout_ms": timeout_ms},
            sandbox_enabled=sandbox_enabled,
        )

    return mcp
