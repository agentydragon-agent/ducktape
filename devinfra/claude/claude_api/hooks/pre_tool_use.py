"""Pydantic models for Claude Code PreToolUse hook.

See https://code.claude.com/docs/en/hooks for the full API spec.
"""

from enum import StrEnum
from typing import Any, Literal

from devinfra.claude.claude_api.hooks.common import CamelModel, HookInputBase


class PermissionDecision(StrEnum):
    """PreToolUse permission decision values."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PreToolUseInput(HookInputBase):
    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str


class PreToolUseDecision(CamelModel):
    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    permission_decision: PermissionDecision
    permission_decision_reason: str


class PreToolUseOutput(CamelModel):
    hook_specific_output: PreToolUseDecision
