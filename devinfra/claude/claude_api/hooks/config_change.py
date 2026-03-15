"""Pydantic models for Claude Code ConfigChange hook."""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from devinfra.claude.claude_api.hooks.common import CamelModel, HookInputBase


class ConfigChangeSource(StrEnum):
    USER_SETTINGS = "user_settings"
    PROJECT_SETTINGS = "project_settings"
    LOCAL_SETTINGS = "local_settings"
    POLICY_SETTINGS = "policy_settings"
    SKILLS = "skills"


class ConfigChangeInput(HookInputBase):
    hook_event_name: Literal["ConfigChange"] = "ConfigChange"
    source: ConfigChangeSource
    file_path: Path | None = Field(default=None, description="Path to changed file; absent for some source types")


class ConfigChangeOutput(CamelModel):
    decision: Literal["block"] | None = Field(default=None, description="Set to 'block' to reject the config change")
    reason: str | None = None
    continue_: bool = Field(default=True, alias="continue")
    suppress_output: bool = False
