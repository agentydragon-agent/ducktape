"""Pydantic models for Claude Code SessionStart hook input.

See https://docs.anthropic.com/en/docs/claude-code/hooks for the full API spec.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


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


class HookInput(BaseModel):
    """Input passed to Claude Code SessionStart hooks via stdin.

    Note: permission_mode defaults to "default" because Claude Code Web was
    observed (2025-01-18) not sending it for SessionStart:resume events.
    """

    session_id: str
    cwd: Path
    transcript_path: str
    model: str = ""
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    hook_event_name: Literal["SessionStart"]
    source: HookSource
