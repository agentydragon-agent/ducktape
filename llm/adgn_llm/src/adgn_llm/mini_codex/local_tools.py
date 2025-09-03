from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Any

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
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd,
    )
    try:
        out, err = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return (
            124,
            _truncate_bytes(out, TRUNCATE_BYTES),
            _truncate_bytes(err + "\n[TIMEOUT]", TRUNCATE_BYTES),
        )

    return (
        p.returncode,
        _truncate_bytes(out, TRUNCATE_BYTES),
        _truncate_bytes(err, TRUNCATE_BYTES),
    )


def _run_in_sandbox(cmd: list[str], timeout_s: int, cwd: str | None) -> tuple[int, str, str]:
    # On non-Linux, require explicit override to run unsandboxed
    if sys.platform != "linux":
        if ALLOW_UNSANDBOXED:
            return _run_proc(cmd, timeout_s=timeout_s, cwd=cwd)
        return (2, "", "sandbox unavailable on this platform; set DUCK_ALLOW_UNSANDBOXED=1 to override")

    # Linux: attempt bubblewrap if available
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


EXEC_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cmd": {"type": "array", "items": {"type": "string"}},
        "cwd": {"type": "string"},
        "timeout_ms": {"type": "integer"},
    },
    "required": ["cmd"],
    "additionalProperties": False,
}

def exec_handler(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a shell command with optional cwd/timeout.

    Args schema:
      - cmd: list[str] (required)
      - cwd: str (optional)
      - timeout_ms: int (optional)
    """
    cmd = args.get("cmd")
    if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
        return {"exit": 2, "stdout": "", "stderr": "invalid cmd"}

    timeout_ms = args.get("timeout_ms")
    to = (
        DEFAULT_TIMEOUT_S if not isinstance(timeout_ms, int) else max(1, int(timeout_ms / 1000))
    )
    cwd_val = args.get("cwd") if isinstance(args.get("cwd"), str) else None

    code, out, err = _run_in_sandbox(cmd, timeout_s=to, cwd=cwd_val)
    return {"exit": code, "stdout": out, "stderr": err}


def build_local_tools() -> dict[str, dict[str, tuple[str, dict[str, Any], Any]]]:
    """Return mapping suitable for McpManager.from_config(..., local=...)."""
    return {
        "local": {
            "exec": (
                "Execute a shell command and return exit, stdout, stderr.",
                EXEC_PARAMETERS_SCHEMA,
                exec_handler,
            ),
        },
    }
