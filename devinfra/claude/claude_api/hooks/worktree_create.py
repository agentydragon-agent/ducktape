"""Pydantic models for Claude Code WorktreeCreate hook."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class WorktreeCreateInput(BaseModel):
    """WorktreeCreate input (no permission_mode field)."""

    session_id: str
    transcript_path: Path
    cwd: Path
    hook_event_name: Literal["WorktreeCreate"] = "WorktreeCreate"
    name: str
