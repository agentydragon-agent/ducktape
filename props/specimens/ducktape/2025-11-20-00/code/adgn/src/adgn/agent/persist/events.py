from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from mcp import types as mcp_types
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from . import EventType


# Canonical typed payloads per event type
class UserTextPayload(BaseModel):
    text: str


class AssistantTextPayload(BaseModel):
    text: str


class ToolCallPayload(BaseModel):
    name: str
    args_json: str | None = None
    call_id: str


class FunctionCallOutputPayload(BaseModel):
    call_id: str
    # Embed Pydantic MCP CallToolResult (full content when available)
    result: mcp_types.CallToolResult


class ReasoningPayload(BaseModel):
    text: str


class ResponsePayload(BaseModel):
    # Minimal placeholder; expand as needed
    content: JsonValue | None = None


TypedPayload = Annotated[
    UserTextPayload
    | AssistantTextPayload
    | ToolCallPayload
    | FunctionCallOutputPayload
    | ReasoningPayload
    | ResponsePayload,
    Field(discriminator=None),
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

    payload: TypedPayload
    if et == EventType.USER_TEXT:
        payload = UserTextPayload(text=str(payload_raw.get("text", "")))
    elif et == EventType.ASSISTANT_TEXT:
        payload = AssistantTextPayload(text=str(payload_raw.get("text", "")))
    elif et == EventType.TOOL_CALL:
        payload = ToolCallPayload(
            name=str(payload_raw.get("name", "")),
            args_json=payload_raw.get("args_json"),
            call_id=str(payload_raw.get("call_id") or d.get("call_id") or ""),
        )
    elif et == EventType.FUNCTION_CALL_OUTPUT:
        # Persisted payload is the Pydantic MCP CallToolResult JSON (alias field names)
        result = TypeAdapter(mcp_types.CallToolResult).validate_python(payload_raw)
        payload = FunctionCallOutputPayload(call_id=str(d.get("call_id") or ""), result=result)
    elif et == EventType.REASONING:
        payload = ReasoningPayload(text=str(payload_raw.get("text", "")))
    elif et == EventType.RESPONSE:
        payload = ResponsePayload(content=payload_raw)
    else:
        # Fallback to response-like envelope
        payload = ResponsePayload(content=payload_raw)

    return EventRecord(seq=seq, ts=ts, type=et, payload=payload, call_id=call_id, tool_key=tool_key)


def parse_events(items: list[dict[str, Any]]) -> list[EventRecord]:
    return [parse_event(d) for d in items]
