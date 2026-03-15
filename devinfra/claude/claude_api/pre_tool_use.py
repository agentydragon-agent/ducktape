"""Pydantic models for Claude Code PreToolUse hook input/output.

See https://docs.anthropic.com/en/docs/claude-code/hooks for the full API spec.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from devinfra.claude.claude_api.hook_input import PermissionMode


class PermissionDecision(StrEnum):
    """PreToolUse permission decision values."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PreToolUseInput(BaseModel):
    session_id: str
    transcript_path: str
    cwd: str
    permission_mode: PermissionMode
    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str


class PreToolUseDecision(_CamelModel):
    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    permission_decision: PermissionDecision
    permission_decision_reason: str


class PreToolUseOutput(_CamelModel):
    hook_specific_output: PreToolUseDecision
