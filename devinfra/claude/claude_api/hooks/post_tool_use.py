"""Pydantic models for Claude Code PostToolUse hook.

See https://code.claude.com/docs/en/hooks for the full API spec.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from devinfra.claude.claude_api.hooks.common import CamelModel, HookInputBase


class PostToolUseInput(HookInputBase):
    hook_event_name: Literal["PostToolUse"] = "PostToolUse"
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    tool_response: Any


class PostToolUseOutput(CamelModel):
    """PostToolUse hook output per Claude Code API."""

    decision: Literal["block"] | None = Field(
        default=None, description="Set to 'block' to re-prompt Claude with reason feedback"
    )
    reason: str | None = Field(default=None, description="Feedback shown to Claude when decision='block'")
    additional_context: str | None = Field(default=None, description="Non-blocking extra context for Claude")
    continue_: bool = Field(
        default=True, alias="continue", description="False to stop Claude entirely (overrides decision)"
    )
    stop_reason: str | None = Field(default=None, description="User-visible message when continue=false")
    suppress_output: bool = Field(default=False, description="Hide from transcript mode output")

    @model_validator(mode="after")
    def _validate_stop_reason(self) -> PostToolUseOutput:
        if self.stop_reason is not None and self.continue_:
            raise ValueError("stop_reason requires continue=false")
        return self
