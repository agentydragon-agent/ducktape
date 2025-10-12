from __future__ import annotations

from pathlib import Path
import subprocess

from adgn.mcp.exec_common.models import StreamOut


def emit_stream(out_b: bytes, limit: int) -> str | StreamOut:
    """Normalize a captured stream into text or a truncated payload."""
    total = len(out_b)
    if total <= limit:
        return out_b.decode("utf-8", errors="replace")
    return StreamOut(
        truncated_text=out_b[:limit].decode("utf-8", errors="replace"),
        total_bytes=total,
    )


def run_proc(
    argv: list[str],
    timeout_s: float,
    cwd: Path | None = None,
    stdin_b: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    """Execute a subprocess, enforcing a timeout and returning collected streams."""
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        cwd=cwd,
    )
    try:
        out, err = proc.communicate(input=(stdin_b or b""), timeout=timeout_s)
        return (proc.returncode, out or b"", err or b"")
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out, err = b"", b""
        return (124, out or b"", (err or b"") + b"\n[TIMEOUT]")
