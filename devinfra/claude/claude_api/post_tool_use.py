"""Pydantic models for Claude Code PostToolUse hook input/output.

See https://docs.anthropic.com/en/docs/claude-code/hooks for the full API spec.
Schema: https://json.schemastore.org/claude-code-settings.json
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from devinfra.claude.claude_api.permission_mode import PermissionMode


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PostToolUseInput(BaseModel):
    session_id: str
    transcript_path: Path
    cwd: Path
    permission_mode: PermissionMode
    hook_event_name: Literal["PostToolUse"] = "PostToolUse"
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    tool_response: str = ""


class PostToolUseOutput(_CamelModel):
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
