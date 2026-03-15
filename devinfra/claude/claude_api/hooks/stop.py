"""Pydantic models for Claude Code Stop and SubagentStop hooks."""

from typing import Literal

from pydantic import Field

from devinfra.claude.claude_api.hooks.common import CamelModel, HookInputBase


class StopInput(HookInputBase):
    hook_event_name: Literal["Stop"] = "Stop"
    stop_hook_active: bool
    last_assistant_message: str


class StopOutput(CamelModel):
    decision: Literal["block"] | None = Field(default=None, description="Set to 'block' to prevent stopping")
    reason: str | None = Field(default=None, description="Feedback to Claude when decision='block'")
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False


class SubagentStopInput(HookInputBase):
    hook_event_name: Literal["SubagentStop"] = "SubagentStop"
    stop_hook_active: bool
    agent_id: str
    agent_type: str
    agent_transcript_path: str
    last_assistant_message: str


class SubagentStopOutput(CamelModel):
    decision: Literal["block"] | None = Field(default=None, description="Set to 'block' to keep subagent working")
    reason: str | None = Field(default=None, description="Feedback to subagent when decision='block'")
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
