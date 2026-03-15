"""Pydantic models for Claude Code UserPromptSubmit hook."""

from typing import Any, Literal

from pydantic import Field

from devinfra.claude.claude_api.hooks.common import CamelModel, HookInputBase


class UserPromptSubmitInput(HookInputBase):
    hook_event_name: Literal["UserPromptSubmit"] = "UserPromptSubmit"
    prompt: str


class UserPromptSubmitOutput(CamelModel):
    decision: Literal["block"] | None = Field(default=None, description="Set to 'block' to reject the prompt")
    reason: str | None = Field(default=None, description="Message shown to user when decision='block'")
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
    hook_specific_output: dict[str, Any] | None = Field(
        default=None, description="hookSpecificOutput with additionalContext"
    )
