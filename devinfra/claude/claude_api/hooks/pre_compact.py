"""Pydantic models for Claude Code PreCompact hook."""

from enum import StrEnum
from typing import Literal

from devinfra.claude.claude_api.hooks.common import HookInputBase


class CompactTrigger(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


class PreCompactInput(HookInputBase):
    hook_event_name: Literal["PreCompact"] = "PreCompact"
    trigger: CompactTrigger
    custom_instructions: str = ""
