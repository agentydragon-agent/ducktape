"""Pydantic models for hook daemon RPC protocol."""

from pydantic import BaseModel, Field

from devinfra.claude.claude_api.hooks.dispatch_input import AnyHookInput
from devinfra.claude.claude_api.hooks.dispatch_output import AnyHookOutput


class HookRequest(BaseModel):
    """RPC request to hook daemon."""

    hook: AnyHookInput = Field(description="Typed hook input (discriminated union)")
    env: dict[str, str] = Field(description="Caller's os.environ")


class HookResponse(BaseModel):
    """RPC response from hook daemon."""

    output: AnyHookOutput | None = Field(default=None, description="Typed hook output. None for noops.")
