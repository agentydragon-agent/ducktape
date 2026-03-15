"""Pydantic models for Claude Code PostToolUseFailure hook."""

from typing import Any, Literal

from devinfra.claude.claude_api.hooks.common import HookInputBase


class PostToolUseFailureInput(HookInputBase):
    hook_event_name: Literal["PostToolUseFailure"] = "PostToolUseFailure"
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str = ""
    error: str = ""
    is_interrupt: bool = False
