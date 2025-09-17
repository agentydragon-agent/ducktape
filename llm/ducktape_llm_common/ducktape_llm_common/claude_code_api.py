"""Pydantic models for Claude Code hook API requests and responses per Anthropic spec."""

from typing import Any, Literal, NewType
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

SessionID = NewType("SessionID", UUID)


# Base input types for Claude Code hook requests
class BaseHookRequest(BaseModel):
    """Base request for all hooks."""

    session_id: SessionID
    transcript_path: str
    hook_event_name: str

    model_config = {"discriminator": "hook_event_name"}


class PreToolUseRequest(BaseHookRequest):
    """PreToolUse hook request."""

    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    tool_input: dict[str, Any]


class PostToolUseRequest(BaseHookRequest):
    """PostToolUse hook request."""

    hook_event_name: Literal["PostToolUse"]
    tool_name: str
    tool_input: dict[str, Any]
    tool_response: dict[str, Any]


class NotificationRequest(BaseHookRequest):
    """Notification hook request."""

    hook_event_name: Literal["Notification"]
    message: str


class StopRequest(BaseHookRequest):
    """Stop hook request."""

    hook_event_name: Literal["Stop"]
    stop_hook_active: bool


class SubagentStopRequest(BaseHookRequest):
    """SubagentStop hook request."""

    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool


class PreCompactRequest(BaseHookRequest):
    """PreCompact hook request."""

    hook_event_name: Literal["PreCompact"]
    trigger: Literal["manual", "auto"]
    custom_instructions: str


# Base response types for Claude Code hook responses
class BaseResponse(BaseModel):
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


class PreToolResponse(BaseResponse):
    """
    PreToolUse hook response.

    Per docs:
    - decision="approve": Bypasses permission system
    - decision="block": Prevents tool call execution
    - undefined: Uses default permission flow
    """

    decision: Literal["approve", "block"] | None = Field(None)
    reason: str | None = Field(None, description="Explanation for decision")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None, info) -> str | None:
        if info.data.get("decision") == "block" and not v:
            raise ValueError("reason required when decision=block")
        return v


class PostToolResponse(BaseResponse):
    """
    PostToolUse hook response.

    Per docs:
    - decision="block": Automatically prompts Claude with reason
    - undefined: No action taken
    """

    decision: Literal["block"] | None = Field(None)
    reason: str | None = Field(
        None, description="Explanation for decision - automatically prompts Claude if decision=block"
    )


class StopResponse(BaseResponse):
    """
    Stop/SubagentStop hook response.

    Per docs:
    - decision="block": Prevents Claude from stopping
    - undefined: Allows Claude to stop
    """

    decision: Literal["block"] | None = Field(None)
    reason: str | None = Field(None, description="Must provide reason if blocking Claude from stopping")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None, info) -> str | None:
        if info.data.get("decision") == "block" and not v:
            raise ValueError("reason required when decision=block")
        return v


# Union type for automatic discrimination
HookRequest = (
    PreToolUseRequest | PostToolUseRequest | NotificationRequest | StopRequest | SubagentStopRequest | PreCompactRequest
)
