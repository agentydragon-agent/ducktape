"""Shared base classes and enums for Claude Code hook models."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class PermissionMode(StrEnum):
    """Claude Code permission mode values."""

    DEFAULT = "default"
    PLAN = "plan"
    ACCEPT_EDITS = "acceptEdits"
    DONT_ASK = "dontAsk"
    BYPASS_PERMISSIONS = "bypassPermissions"


class CamelModel(BaseModel):
    """Base for hook output models — serializes fields as camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HookInputBase(BaseModel):
    """Common fields present in most hook inputs."""

    session_id: str
    transcript_path: Path
    cwd: Path
    permission_mode: PermissionMode
