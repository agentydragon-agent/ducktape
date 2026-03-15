"""Pydantic models for Claude Code SessionStart hook.

See https://code.claude.com/docs/en/hooks for the full API spec.
"""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from devinfra.claude.claude_api.hooks.common import CamelModel, PermissionMode


class HookSource(StrEnum):
    """Source of the SessionStart hook event."""

    STARTUP = "startup"
    RESUME = "resume"
    CLEAR = "clear"
    COMPACT = "compact"


class SessionStartHookInput(BaseModel):
    """Input for Claude Code SessionStart hooks (parsed from stdin JSON)."""

    session_id: str
    cwd: Path
    transcript_path: Path
    model: str
    permission_mode: PermissionMode | None = Field(
        default=None, description="Not sent by Claude Code Web for SessionStart:resume events (observed 2025-01-18)."
    )
    hook_event_name: Literal["SessionStart"] = "SessionStart"
    source: HookSource


class SessionStartHookSpecificOutput(CamelModel):
    hook_event_name: Literal["SessionStart"] = "SessionStart"
    additional_context: str | None = Field(default=None, description="Context added to Claude's system prompt")


class SessionStartOutput(CamelModel):
    """SessionStart hook stdout JSON output."""

    continue_: bool = Field(default=True, alias="continue", description="False to stop Claude entirely")
    stop_reason: str | None = Field(default=None, description="User-visible message when continue=false")
    suppress_output: bool = Field(default=False, description="Hide from transcript mode output")
    system_message: str | None = Field(default=None, description="Warning shown to user")
    hook_specific_output: SessionStartHookSpecificOutput | None = None
