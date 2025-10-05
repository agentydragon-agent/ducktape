from __future__ import annotations

from pydantic import BaseModel, Field


class ExecInput(BaseModel):
    """Typed payload for container exec tool.

    Prefer passing cmd as a list to avoid shell quoting issues. Set shell=True to run via
    'sh -lc <cmd>' when providing a single string command assembled server-side.
    """

    cmd: list[str] = Field(
        description="Command to run; pass list to avoid shell quoting issues",
    )
    cwd: str | None = Field(default=None, description="Working directory inside container")
    env: dict[str, str] | None = Field(
        default=None,
        description="Environment variables for the process",
    )
    user: str | None = Field(default=None, description="Username inside container")
    tty: bool = Field(default=False, description="Allocate a TTY for the process")
    shell: bool = Field(default=False, description="Run via sh -lc <cmd>")
    timeout_secs: float | None = Field(
        default=None,
        description="Timeout in seconds; sends TERM (exit_code becomes None)",
    )


class ExecResult(BaseModel):
    """Structured output for container exec tool.

    Returned as structuredContent by FastMCP when structured_output=True is set on the tool.
    """

    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
