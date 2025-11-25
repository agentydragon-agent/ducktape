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
    type: EventType
    payload: TypedPayload
    call_id: str | None = None
    tool_key: str | None = None

    model_config = ConfigDict(extra="forbid")


def parse_event(d: dict[str, Any]) -> EventRecord:
    raw_type = d.get("type")
    et = EventType(str(raw_type))
    seq = int(d.get("seq", 0))
    ts_raw = d.get("ts")
    ts = ts_raw if isinstance(ts_raw, datetime) else datetime.fromisoformat(str(ts_raw))
    call_id = d.get("call_id")
    tool_key = d.get("tool_key")
    payload_raw = d.get("payload") or {}

    # Inject type field into payload for discriminated union parsing
    payload_dict = dict(payload_raw)
    payload_dict["type"] = et.value
    payload = TypeAdapter(TypedPayload).validate_python(payload_dict)

    return EventRecord(seq=seq, ts=ts, type=et, payload=payload, call_id=call_id, tool_key=tool_key)


def parse_events(items: list[dict[str, Any]]) -> list[EventRecord]:
    return [parse_event(d) for d in items]
