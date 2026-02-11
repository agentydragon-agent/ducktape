"""Pydantic models for Claude Code hook API requests and responses per Anthropic spec."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, NewType
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SessionID = NewType("SessionID", UUID)


class EditOperation(BaseModel):
    """Individual edit operation for MultiEdit tool."""

    old_string: str
    new_string: str
    replace_all: bool = False


class ToolInput(BaseModel):
    """Input parameters for Claude Code tools.

    Different tools use different subsets of these fields.
    Extra fields are allowed for MCP and other tools.
    """

    model_config = ConfigDict(extra="allow")

    # Common fields
    file_path: str | None = None
    content: str | None = None

    # Edit tool fields
    old_string: str | None = None
    new_string: str | None = None
    replace_all: bool = False
    old_content: str | None = None

    # MultiEdit tool fields
    edits: list[EditOperation] | None = None

    # Bash tool fields
    command: str | None = None

    # MCP tool fields (common ones)
    url: str | None = None
    query: str | None = None
    path: str | None = None
    directory: str | None = None

    # Allow any additional fields for extensibility
    allowDangerous: bool | None = None  # noqa: N815
    wait_for: str | None = None
    database: str | None = None
    endpoint: str | None = None
    method: str | None = None


class HookEventName(StrEnum):
    """Valid hook event names in Claude Code."""

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    NOTIFICATION = "Notification"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"
    PRE_COMPACT = "PreCompact"


# Base input types for Claude Code hook requests
class BaseHookRequest(BaseModel):
    """Base request for all hooks."""

    session_id: str
    transcript_path: str | None = None
    hook_event_name: str

    model_config = ConfigDict(populate_by_name=True)

    @property
    def typed_session_id(self) -> SessionID:
        """Return session_id as a typed SessionID (UUID)."""
        return SessionID(UUID(self.session_id))


class PreToolUseRequest(BaseHookRequest):
    """PreToolUse hook request."""

    hook_event_name: Literal["PreToolUse"] = "PreToolUse"
    tool_name: str
    tool_input: ToolInput

    @model_validator(mode="before")
    @classmethod
    def convert_tool_input(cls, data: Any) -> Any:
        """Convert dict tool_input to ToolInput model."""
        if isinstance(data, dict) and isinstance(data.get("tool_input"), dict):
            data["tool_input"] = ToolInput(**data["tool_input"])
        return data


class PostToolUseRequest(BaseHookRequest):
    """PostToolUse hook request."""

    hook_event_name: Literal["PostToolUse"] = "PostToolUse"
    tool_name: str
    tool_input: ToolInput
    tool_response: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None  # Some versions use tool_result instead

    @model_validator(mode="before")
    @classmethod
    def convert_tool_input(cls, data: Any) -> Any:
        """Convert dict tool_input to ToolInput model."""
        if isinstance(data, dict) and isinstance(data.get("tool_input"), dict):
            data["tool_input"] = ToolInput(**data["tool_input"])
        return data


class NotificationRequest(BaseHookRequest):
    """Notification hook request."""

    hook_event_name: Literal["Notification"] = "Notification"
    message: str = ""
    title: str | None = None


class StopRequest(BaseHookRequest):
    """Stop hook request."""

    hook_event_name: Literal["Stop"] = "Stop"
    stop_hook_active: bool = True


class SubagentStopRequest(BaseHookRequest):
    """SubagentStop hook request."""

    hook_event_name: Literal["SubagentStop"] = "SubagentStop"
    stop_hook_active: bool = True


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
    stop_reason: str | None = Field(
        None, alias="stopReason", description="Message shown to USER when continue is false"
    )
    suppress_output: bool | None = Field(None, alias="suppressOutput")

    model_config = {"populate_by_name": True}

    @field_validator("stop_reason")
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
