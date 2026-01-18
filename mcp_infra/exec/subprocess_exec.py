"""Minimal subprocess execution - no MCP/fastmcp dependencies.

This module provides subprocess execution that can be used by:
- In-container agent loops (no MCP)
- MCP exec servers (via wrapper in direct.py)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


# --- Timeout type ---

MAX_EXEC_TIMEOUT_MS = 300_000
TimeoutMs = Annotated[int, Field(gt=0, le=MAX_EXEC_TIMEOUT_MS)]


# --- Input model ---


class ExecArgs(BaseModel):
    """Arguments for subprocess execution."""

    cmd: list[str]
    max_bytes: int = Field(default=50_000, ge=0, le=100_000, description="Max bytes for stdout/stderr")
    cwd: str | None = None
    timeout_ms: TimeoutMs = Field(default=30_000)
    stdin_text: str | None = None

    model_config = ConfigDict(extra="forbid")


# --- Output models ---


class TruncatedStream(BaseModel):
    """Truncated stream output with metadata."""

    truncated_text: str
    total_bytes: int


ExecStream = str | TruncatedStream


class TimedOut(BaseModel):
    """Process was terminated after exceeding the timeout."""

    kind: Literal["timed_out"] = "timed_out"


class Exited(BaseModel):
    """Process exited normally with an exit code."""

    kind: Literal["exited"] = "exited"
    exit_code: int


class Killed(BaseModel):
    """Process was killed by a signal."""

    kind: Literal["killed"] = "killed"
    signal: int


ExitStatus = Annotated[TimedOut | Exited | Killed, Field(discriminator="kind")]


class ExecResult(BaseModel):
    """Result from subprocess execution."""

    exit: ExitStatus
    stdout: ExecStream
    stderr: ExecStream
    duration_ms: int = Field(description="Execution duration in milliseconds")

    model_config = ConfigDict(extra="forbid")


# --- Internal types ---


@dataclass(frozen=True)
class _ExecOutput:
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class _ExecOutcome:
    output: _ExecOutput
    exit: ExitStatus
    duration_ms: int


# --- Helper functions ---


@asynccontextmanager
async def _async_timer() -> AsyncGenerator[Callable[[], int]]:
    loop = asyncio.get_running_loop()
    start_time = loop.time()

    def get_duration_ms() -> int:
        return round((loop.time() - start_time) * 1000)

    yield get_duration_ms


def _render_stream(data: bytes, limit: int) -> ExecStream:
    if limit <= 0 or len(data) == 0:
        return ""
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace")
    return TruncatedStream(truncated_text=data[:limit].decode("utf-8", errors="replace"), total_bytes=len(data))


def _render_outcome(outcome: _ExecOutcome, max_bytes: int) -> ExecResult:
    return ExecResult(
        exit=outcome.exit,
        stdout=_render_stream(outcome.output.stdout, max_bytes),
        stderr=_render_stream(outcome.output.stderr, max_bytes),
        duration_ms=outcome.duration_ms,
    )


# --- Subprocess execution ---


async def _run_subprocess(
    argv: list[str], timeout_s: float, *, cwd: Path | None = None, stdin: str | None = None
) -> _ExecOutcome:
    stdin_bytes = stdin.encode("utf-8", errors="replace") if stdin else None

    async with _async_timer() as get_duration_ms:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            out, err = await asyncio.wait_for(proc.communicate(input=stdin_bytes), timeout=timeout_s)

            stdout_bytes = out if out is not None else b""
            stderr_bytes = err if err is not None else b""
            exit_code = proc.returncode if proc.returncode is not None else 0
            output = _ExecOutput(stdout=stdout_bytes, stderr=stderr_bytes)

            if exit_code < 0:
                return _ExecOutcome(output=output, exit=Killed(signal=-exit_code), duration_ms=get_duration_ms())

            return _ExecOutcome(output=output, exit=Exited(exit_code=exit_code), duration_ms=get_duration_ms())

        except TimeoutError:
            proc.kill()
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
            except (TimeoutError, ProcessLookupError):
                out, err = b"", b""
            stdout_bytes = out if out is not None else b""
            stderr_bytes = err if err is not None else b""
            output = _ExecOutput(stdout=stdout_bytes, stderr=stderr_bytes)
            return _ExecOutcome(output=output, exit=TimedOut(), duration_ms=get_duration_ms())


async def run_exec(args: ExecArgs, *, default_cwd: Path | None = None) -> ExecResult:
    """Execute a subprocess and return the result.

    Args:
        args: Execution arguments (command, timeout, etc.)
        default_cwd: Fallback working directory if args.cwd is not specified

    Raises:
        ValueError: If cmd is empty or contains non-strings
    """
    if not args.cmd or not all(isinstance(x, str) for x in args.cmd):
        raise ValueError("cmd must be a non-empty list[str]")

    cwd_val = Path(args.cwd) if args.cwd else default_cwd
    timeout_s = max(0.001, args.timeout_ms / 1000.0)

    outcome = await _run_subprocess(args.cmd, timeout_s, cwd=cwd_val, stdin=args.stdin_text)
    return _render_outcome(outcome, args.max_bytes)


def get_exec_tool_schema() -> dict:
    """Return the exec tool schema for OpenAI."""
    parameters = ExecArgs.model_json_schema()
    parameters.pop("$defs", None)
    return {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Execute a shell command in the workspace. Use for code analysis (cat, rg, grep, find, etc.).",
            "parameters": parameters,
            "strict": True,
        },
    }
