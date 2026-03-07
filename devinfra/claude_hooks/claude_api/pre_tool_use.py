"""Pydantic models for Claude Code PreToolUse hook input/output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PreToolUseInput(BaseModel):
    session_id: str
    transcript_path: str
    cwd: str
    permission_mode: Literal["default", "plan", "acceptEdits", "dontAsk", "bypassPermissions"]
    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str


class PreToolUseDecision(_CamelModel):
    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    permission_decision: Literal["allow", "deny", "ask"]
    permission_decision_reason: str


class PreToolUseOutput(_CamelModel):
    hook_specific_output: PreToolUseDecision
