"""Pydantic models for hook daemon RPC protocol."""

from typing import Literal

from pydantic import BaseModel, Field

from devinfra.claude.claude_api.hooks.dispatch_input import AnyHookInput
from devinfra.claude.claude_api.hooks.output import HookOutput


class HookRequest(BaseModel):
    """RPC request to hook daemon."""

    hook: AnyHookInput = Field(description="Typed hook input (discriminated union)")
    env: dict[str, str] = Field(description="Caller's os.environ")


class HookResponse(BaseModel):
    """RPC response from hook daemon."""

    output: HookOutput | None = Field(default=None, description="Typed hook output. None for noops.")


class ShimExecRequest(BaseModel):
    """RPC from a shim (bazelisk, git) reporting that it is about to exec."""

    shim: str = Field(description="Shim name: 'bazelisk', 'git'")
    session_id: str = Field(description="Session ID (from DUCKTAPE_CLAUDE_HOOKS_SESSION_DIR basename)")
    cwd: str = Field(description="Working directory of the shim process")
    argv: list[str] = Field(description="Full argv including argv[0]")
    env: dict[str, str] = Field(description="Environment variables of the shim process")


class ShimBlocked(BaseModel):
    """Server blocked the command — shim must print message and exit 1."""

    kind: Literal["blocked"] = "blocked"
    message: str = Field(description="Message to print to stderr.")


class ShimExecve(BaseModel):
    """Server approved — shim should resolve binary and execvp with this argv."""

    kind: Literal["execve"] = "execve"
    argv: list[str] = Field(description="Args to exec with. Server may inject flags (e.g. --bazelrc for bazelisk).")
