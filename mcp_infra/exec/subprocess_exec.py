"""Minimal subprocess execution for in-container agent loops.

Provides exec tool without fastmcp dependency. Uses types from models.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mcp_infra.exec.models import BaseExecResult, TimeoutMs, render_outcome_to_result
from mcp_infra.exec.subprocess import run_proc


class ExecArgs(BaseModel):
    """Arguments for shell command execution."""

    cmd: list[str] = Field(
        description="Command array passed directly to subprocess (no shell). "
        "DO NOT include shell quotes around arguments - array elements are passed as-is. "
        "For shell features (pipes, globs), use: ['sh', '-c', 'command | pipe']"
    )
    max_bytes: int = Field(100_000, ge=0, le=100_000, description="Max bytes to capture from stdout/stderr")
    cwd: str | None = Field(None, description="Working directory (None = current directory)")
    timeout_ms: TimeoutMs = Field(description="Timeout in milliseconds")
    stdin_text: str | None = Field(None, description="Text to send to stdin")

    model_config = ConfigDict(extra="forbid")


def get_exec_tool_schema() -> dict[str, Any]:
    """Return OpenAI-compatible tool schema for the exec tool."""
    return {
        "type": "function",
        "name": "exec",
        "description": "Execute a shell command. Use for file operations, running tests, etc.",
        "parameters": ExecArgs.model_json_schema(),
    }


async def run_exec(args: ExecArgs, *, default_cwd: Path | None = None) -> BaseExecResult:
    """Execute a command and return the result.

    Args:
        args: Exec arguments (command, timeout, etc.)
        default_cwd: Fallback working directory if args.cwd is not specified

    Raises:
        ValueError: If cmd is empty or contains non-strings
    """
    if not args.cmd or not all(isinstance(x, str) for x in args.cmd):
        raise ValueError("INVALID_CMD: cmd must be a non-empty list[str]")

    cwd_val: Path | None = Path(args.cwd) if args.cwd else None
    if cwd_val is None and default_cwd is not None:
        cwd_val = default_cwd

    timeout_s = max(0.001, args.timeout_ms / 1000.0)
    outcome = await run_proc(args.cmd, timeout_s, cwd=cwd_val, stdin=args.stdin_text)
    return render_outcome_to_result(outcome, args.max_bytes)
