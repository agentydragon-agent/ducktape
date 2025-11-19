"""Shared types for the agent package."""

from typing import NewType

from pydantic import BaseModel

AgentID = NewType("AgentID", str)


class ToolCall(BaseModel):
    """Tool call information (simple version without discriminator)."""

    name: str
    call_id: str
    args_json: str | None
