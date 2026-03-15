"""Pydantic models for Claude Code WorktreeRemove hook."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class WorktreeRemoveInput(BaseModel):
    """WorktreeRemove input (no permission_mode field)."""

    session_id: str
    transcript_path: Path
    cwd: Path
    hook_event_name: Literal["WorktreeRemove"] = "WorktreeRemove"
    worktree_path: Path
