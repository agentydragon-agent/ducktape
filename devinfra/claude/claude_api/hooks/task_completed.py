"""Pydantic models for Claude Code TaskCompleted hook."""

from typing import Literal

from devinfra.claude.claude_api.hooks.common import HookInputBase


class TaskCompletedInput(HookInputBase):
    hook_event_name: Literal["TaskCompleted"] = "TaskCompleted"
    task_id: str = ""
    task_subject: str = ""
    task_description: str = ""
    teammate_name: str = ""
    team_name: str = ""
