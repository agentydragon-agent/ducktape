"""Pydantic models for Claude Code SessionEnd hook."""

from enum import StrEnum
from typing import Literal

from devinfra.claude.claude_api.hooks.common import HookInputBase


class SessionEndReason(StrEnum):
    CLEAR = "clear"
    LOGOUT = "logout"
    PROMPT_INPUT_EXIT = "prompt_input_exit"
    BYPASS_PERMISSIONS_DISABLED = "bypass_permissions_disabled"
    OTHER = "other"


class SessionEndInput(HookInputBase):
    hook_event_name: Literal["SessionEnd"] = "SessionEnd"
    reason: SessionEndReason
