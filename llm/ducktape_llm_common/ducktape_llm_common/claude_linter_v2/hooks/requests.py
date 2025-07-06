"""Hook-specific request models matching Anthropic's hook inputs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..types import SessionID, parse_session_id


class BaseHookRequest(BaseModel):
    """Common fields for all hook requests."""

    session_id: str = Field(description="Claude Code session ID (required)")
    transcript_path: str | None = Field(None, description="Path to session transcript")
    hook_event_name: str = Field(description="Hook type name")

    @property
    def typed_session_id(self) -> SessionID:
        """Get typed session ID (always present)."""
        return parse_session_id(self.session_id)


class EditInput(BaseModel):
    """Edit tool input structure."""

    old_string: str
    new_string: str
    replace_all: bool = False


class ToolInput(BaseModel):
    """Tool-specific input data."""

    # Common fields
    file_path: str | None = None
    content: str | None = None
    old_content: str | None = None
    command: str | None = None
    # Edit tool specific
    old_string: str | None = None
    new_string: str | None = None
    replace_all: bool | None = None
    # MultiEdit tool specific
    edits: list[EditInput] | None = None
    # Search/Grep tool specific
    pattern: str | None = None
    path: str | None = None
    include: str | None = None

    class Config:
        extra = "allow"  # Allow extra fields for unknown tools


class PreToolUseRequest(BaseHookRequest):
    """PreToolUse hook request."""

    tool_name: str = Field(description="Tool being invoked")
    tool_input: ToolInput = Field(description="Tool parameters")
    request_id: str | None = None
    timestamp: datetime | None = None


class PostToolUseRequest(PreToolUseRequest):
    """PostToolUse hook request - same as PreTool plus result."""

    tool_result: Any = Field(None, description="Tool execution result")
    tool_response: Any = Field(None, description="Tool response data (alias for tool_result)")


class StopRequest(BaseHookRequest):
    """Stop hook request."""

    stop_hook_active: bool | None = Field(None, description="Whether stop hook is active")
    # Additional stop-specific fields


class SubagentStopRequest(StopRequest):
    """SubagentStop hook request."""

    task_id: str | None = None
    task_description: str | None = None


class NotificationRequest(BaseHookRequest):
    """Notification hook request from Claude Code."""

    message: str | None = None
    title: str | None = None
