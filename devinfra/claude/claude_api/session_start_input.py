"""Pydantic models for Claude Code SessionStart hook input.

See https://docs.anthropic.com/en/docs/claude-code/hooks for the full API spec.
Schema: https://json.schemastore.org/claude-code-settings.json
"""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class PermissionMode(StrEnum):
    """Claude Code permission mode values."""

    DEFAULT = "default"
    PLAN = "plan"
    ACCEPT_EDITS = "acceptEdits"
    DONT_ASK = "dontAsk"
    BYPASS_PERMISSIONS = "bypassPermissions"


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
    model: str = ""
    permission_mode: PermissionMode | None = Field(
        default=None, description="Not sent by Claude Code Web for SessionStart:resume events (observed 2025-01-18)."
    )
    hook_event_name: Literal["SessionStart"] = "SessionStart"
    source: HookSource


# Backwards compatibility alias
HookInput = SessionStartHookInput
