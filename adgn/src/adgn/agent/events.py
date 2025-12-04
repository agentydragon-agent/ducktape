"""Agent event types"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from adgn.openai_utils.model import InputTokensDetails, OutputTokensDetails, ReasoningItem

__all__ = [
    "AssistantText",
    "EventType",
    "GroundTruthUsage",
    "ReasoningItem",
    "Response",
    "ToolCall",
    "ToolCallOutput",
    "UserText",
]


# ---- Ground-truth usage (OpenAI upstream fields only; no derived numbers) ----
class GroundTruthUsage(BaseModel):
    model: str
    input_tokens: int | None = None
    input_tokens_details: InputTokensDetails | None = None
    output_tokens: int | None = None
    output_tokens_details: OutputTokensDetails | None = None
    total_tokens: int | None = None


# ---- Typed events (discriminated by "type" field) ----
class UserText(BaseModel):
    type: Literal["user_text"] = "user_text"
    text: str


class AssistantText(BaseModel):
    type: Literal["assistant_text"] = "assistant_text"
    text: str


class ToolCall(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    name: str
    args_json: str | None = None
    call_id: str


class ToolCallOutput(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    result: CallToolResult


class Response(BaseModel):
    """One OpenAI responses.create result (non-streaming) with usage.

    Emitted once per model call to avoid duplicating usage across assistant/tool events.
    """

    type: Literal["response"] = "response"
    response_id: str
    usage: GroundTruthUsage
    model: str
    created_at: datetime | None = None
    idempotency_key: str | None = None


# Union of all current event types (discriminated by "type" field)
EventType = Annotated[
    UserText | AssistantText | ToolCall | ToolCallOutput | Response | ReasoningItem, Field(discriminator="type")
]
