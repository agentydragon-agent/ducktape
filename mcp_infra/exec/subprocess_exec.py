"""Minimal subprocess execution for in-container agent loops.

Provides exec tool without fastmcp dependency. Uses types from models.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import Field

from mcp_infra.exec.models import (
    BaseExecResult,
    ExecOutcome,
    ExecOutput,
    Exited,
    Killed,
    TimedOut,
    TimeoutMs,
    async_timer,
    render_outcome_to_result,
)
from openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel


def _make_output(out: bytes | None, err: bytes | None) -> ExecOutput:
    """Create ExecOutput from stdout/stderr byte streams."""
    return ExecOutput(
        stdout=out if out is not None else b"",
        stderr=err if err is not None else b"",
    )


async def run_proc(
    argv: list[str], timeout_s: float, *, cwd: Path | None = None, stdin: bytes | str | None = None
) -> ExecOutcome:
    """Run a subprocess with timeout, returning structured outcome."""
    if stdin is None:
        stdin_bytes: bytes | None = None
    elif isinstance(stdin, str):
        stdin_bytes = stdin.encode("utf-8", errors="replace")
    else:
        stdin_bytes = stdin

    async with async_timer() as get_duration_ms:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            out, err = await asyncio.wait_for(proc.communicate(input=stdin_bytes), timeout=timeout_s)
            output = _make_output(out, err)
            exit_code = proc.returncode if proc.returncode is not None else 0

            # Detect if process was killed by signal (negative exit code on Unix)
            if exit_code < 0:
                signal_num = -exit_code
                return ExecOutcome(output=output, exit=Killed(signal=signal_num), duration_ms=get_duration_ms())

            return ExecOutcome(output=output, exit=Exited(exit_code=exit_code), duration_ms=get_duration_ms())

        except TimeoutError:
            proc.kill()
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
            except (TimeoutError, ProcessLookupError):
                out, err = b"", b""
            return ExecOutcome(output=_make_output(out, err), exit=TimedOut(), duration_ms=get_duration_ms())


class SubprocessExecArgs(OpenAIStrictModeBaseModel):
    """Arguments for subprocess execution (OpenAI strict mode compatible)."""

    cmd: list[str] = Field(
        min_length=1,
        description="Command array passed directly to subprocess (no shell). "
        "DO NOT include shell quotes around arguments - array elements are passed as-is. "
        "For shell features (pipes, globs), use: ['sh', '-c', 'command | pipe']",
    )
    max_bytes: int = Field(100_000, ge=0, le=100_000, description="Max bytes to capture from stdout/stderr")
    cwd: str | None = Field(None, description="Working directory (None = current directory)")
    timeout_ms: TimeoutMs = Field(description="Timeout in milliseconds")
    stdin_text: str | None = Field(None, description="Text to send to stdin")


async def run_exec(args: SubprocessExecArgs, *, default_cwd: Path | None = None) -> BaseExecResult:
    """Execute a command and return the result."""
    cwd_val = Path(args.cwd) if args.cwd else default_cwd
    timeout_s = max(0.001, args.timeout_ms / 1000.0)
    outcome = await run_proc(args.cmd, timeout_s, cwd=cwd_val, stdin=args.stdin_text)
    return render_outcome_to_result(outcome, args.max_bytes)
