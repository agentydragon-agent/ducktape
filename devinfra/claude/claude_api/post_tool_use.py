"""Pydantic models for Claude Code PostToolUse hook input/output.

See https://docs.anthropic.com/en/docs/claude-code/hooks for the full API spec.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from devinfra.claude.claude_api.hook_input import PermissionMode


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PostToolUseInput(BaseModel):
    session_id: str
    transcript_path: str
    cwd: str
    permission_mode: PermissionMode
    hook_event_name: Literal["PostToolUse"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    tool_response: str = ""


class PostToolUseOutput(_CamelModel):
    """PostToolUse hook output per Claude Code API.

    Fields:
        decision: Set to "block" to re-prompt Claude with reason feedback.
        reason: Feedback shown to Claude when decision="block".
        additional_context: Non-blocking extra context for Claude.
        continue_: False to stop Claude entirely (overrides decision).
        stop_reason: User-visible message when continue=false.
        suppress_output: Hide from transcript mode output.
    """

    decision: Literal["block"] | None = None
    reason: str | None = None
    additional_context: str | None = None
    continue_: bool = Field(default=True, alias="continue")
    stop_reason: str | None = None
    suppress_output: bool = False
