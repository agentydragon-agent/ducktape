"""Pydantic models for Claude Code WorktreeCreate hook."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from devinfra.claude.claude_api.hooks.common import CamelModel, HookOutputBase


class WorktreeCreateInput(BaseModel):
    """WorktreeCreate input (no permission_mode field)."""

    session_id: str
    transcript_path: Path
    cwd: Path
    hook_event_name: Literal["WorktreeCreate"] = "WorktreeCreate"
    name: str


class WorktreeCreateHookSpecificOutput(CamelModel):
    hook_event_name: Literal["WorktreeCreate"] = "WorktreeCreate"
    worktree_path: str = Field(description="Absolute path to the created worktree directory")


class WorktreeCreateOutput(HookOutputBase):
    hook_specific_output: WorktreeCreateHookSpecificOutput | None = None
