"""Shared types for the agent package."""

from typing import NewType

from pydantic import BaseModel, Field

AgentID = NewType("AgentID", str)


class ToolCall(BaseModel):
    """Tool call information (simple version without discriminator)."""

    name: str = Field(description="Tool name")
    call_id: str = Field(description="Unique call identifier")
    args_json: str | None = Field(None, description="Tool arguments as JSON string")
