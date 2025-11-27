from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from mcp import types as mcp_types
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from . import EventType


# Canonical typed payloads per event type
class UserTextPayload(BaseModel):
    type: Literal["user_text"] = "user_text"
    text: str


class AssistantTextPayload(BaseModel):
    type: Literal["assistant_text"] = "assistant_text"
    text: str


class ToolCallPayload(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    name: str
    args_json: str | None = None
    call_id: str


class FunctionCallOutputPayload(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    # Embed Pydantic MCP CallToolResult (full content when available)
    result: mcp_types.CallToolResult


class ReasoningPayload(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    text: str


class ResponsePayload(BaseModel):
    type: Literal["response"] = "response"
    # Minimal placeholder; expand as needed
    content: Any | None = None


TypedPayload = Annotated[
    UserTextPayload
    | AssistantTextPayload
    | ToolCallPayload
    | FunctionCallOutputPayload
    | ReasoningPayload
    | ResponsePayload,
    Field(discriminator="type"),
]


class EventRecord(BaseModel):
    seq: int
    ts: datetime
    payload: TypedPayload
    call_id: str | None = None
    tool_key: str | None = None

    model_config = ConfigDict(extra="forbid")


def parse_event(d: dict[str, Any]) -> EventRecord:
    return EventRecord.model_validate(d)


def parse_events(items: list[dict[str, Any]]) -> list[EventRecord]:
    return [parse_event(d) for d in items]
