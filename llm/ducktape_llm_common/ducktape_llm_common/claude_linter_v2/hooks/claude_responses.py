"""Pydantic models for Claude Code hook responses per Anthropic spec."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ClaudeBaseResponse(BaseModel):
    """
    Base response for all hooks.

    Per Anthropic docs section "Common JSON Fields":
    - continue: Whether Claude should continue (default: true)
    - stopReason: Message shown when continue is false (shown to user, NOT Claude)
    - suppressOutput: Hide stdout from transcript mode
    """

    continue_: bool = Field(True, alias="continue")
    stopReason: str | None = Field(None, description="Message shown to USER when continue is false")
    suppressOutput: bool | None = Field(None)

    model_config = {"populate_by_name": True}

    @field_validator("stopReason")
    @classmethod
    def validate_stop_reason(cls, v: str | None, info) -> str | None:
        if v and info.data.get("continue_", True):
            raise ValueError("stopReason only valid when continue=False")
        return v


class ClaudePreToolResponse(ClaudeBaseResponse):
    """
    PreToolUse hook response.

    Per docs:
    - decision="approve": reason shown to user but NOT Claude
    - decision="block": reason shown to Claude for retry
    """

    decision: Literal["approve", "block"] | None = Field(None)
    reason: str | None = Field(None, description="Message target depends on decision value")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None, info) -> str | None:
        if info.data.get("decision") == "block" and not v:
            raise ValueError("reason required when decision=block")
        return v


class ClaudePostToolResponse(ClaudeBaseResponse):
    """
    PostToolUse hook response.

    Per docs: reason used to "automatically prompt Claude" if decision=block
    """

    decision: Literal["continue", "block"] | None = Field(None)
    reason: str | None = Field(None, description="Feedback for Claude when decision=block")


class ClaudeStopResponse(ClaudeBaseResponse):
    """
    Stop/SubagentStop hook response.

    Per docs: "block" prevents Claude from stopping, must provide reason
    Note: There's no mechanism for user-only messages in Stop hooks
    """

    decision: Literal["block"] | None = Field(None)
    reason: str | None = Field(None, description="Shown to Claude when blocked from stopping")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None, info) -> str | None:
        if info.data.get("decision") == "block" and not v:
            raise ValueError("reason required when decision=block")
        return v
