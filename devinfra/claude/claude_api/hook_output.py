"""Common base models for Claude Code hook JSON output.

All hooks share common top-level output fields (continue, stopReason, etc.).
Hook-specific output goes in hookSpecificOutput with a hookEventName discriminator.

See https://code.claude.com/docs/en/hooks for the full API spec.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SessionStartHookSpecificOutput(_CamelModel):
    hook_event_name: Literal["SessionStart"] = "SessionStart"
    additional_context: str | None = Field(default=None, description="Context added to Claude's system prompt")


class SessionStartOutput(_CamelModel):
    """SessionStart hook stdout JSON output."""

    continue_: bool = Field(default=True, alias="continue", description="False to stop Claude entirely")
    stop_reason: str | None = Field(default=None, description="User-visible message when continue=false")
    suppress_output: bool = Field(default=False, description="Hide from transcript mode output")
    system_message: str | None = Field(default=None, description="Warning shown to user")
    hook_specific_output: SessionStartHookSpecificOutput | None = None
