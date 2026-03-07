"""Pydantic models for Claude Code SessionStart hook input."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class HookSource(StrEnum):
    """Source of the SessionStart hook event."""

    STARTUP = "startup"
    RESUME = "resume"
    CLEAR = "clear"
    COMPACT = "compact"


class HookInput(BaseModel):
    """Input passed to Claude Code hooks via stdin.

    Note: permission_mode is optional because Claude Code Web was observed
    (2025-01-18) not sending it for SessionStart:resume events, despite
    documentation claiming it's required.
    """

    session_id: str
    cwd: Path
    transcript_path: str
    permission_mode: Literal["default", "plan", "acceptEdits", "dontAsk", "bypassPermissions"] = "default"
    hook_event_name: Literal["SessionStart"]
    source: HookSource
