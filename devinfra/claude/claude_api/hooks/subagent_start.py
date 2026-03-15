"""Pydantic models for Claude Code SubagentStart hook."""

from typing import Literal

from devinfra.claude.claude_api.hooks.common import HookInputBase


class SubagentStartInput(HookInputBase):
    hook_event_name: Literal["SubagentStart"] = "SubagentStart"
    agent_id: str = ""
    agent_type: str = ""
