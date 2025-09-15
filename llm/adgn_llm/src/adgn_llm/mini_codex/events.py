"""Typed event classes for MiniCodex (no enums, no base class required).

from __future__ import annotations


These models are used internally for handler dispatch and for serializing
structured transcript lines. A tiny helper maps types to the JSONL `kind`.

Scope (first pass): user/assistant text and tool call I/O. Reasoning/system
notes can be added similarly if/when needed.
"""

from datetime import datetime
from typing import Any, Literal, Union, TypedDict

from pydantic import BaseModel


class GroundTruthUsage(BaseModel):
    """Upstream usage fields as returned by OpenAI (no derived numbers).

    Optional fields are omitted if the API omits them; estimation is set only
    when we infer counts offline.
    """

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int | None = None
    reasoning_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    request_id: str | None = None
    response_id: str | None = None
    created_at: datetime | None = None
    idempotency_key: str | None = None
    estimation: dict[str, str] | None = None  # e.g., {"method": "tokenizer"}


class UserText(BaseModel):
    text: str


class AssistantText(BaseModel):
    text: str


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any]
    call_id: str


class FunctionCallOutput(BaseModel):
    call_id: str
    output: str


class Response(BaseModel):
    """One OpenAI responses.create result (non-streaming) with usage.

    Emitted once per model call to avoid duplicating usage across assistant/tool events.
    """

    response_id: str | None = None
    usage: GroundTruthUsage
    model: str | None = None
    created_at: datetime | None = None
    idempotency_key: str | None = None


# Union of all current event types
EventType = Union[UserText, AssistantText, ToolCall, FunctionCallOutput, Response]


# Lightweight type->kind map for transcript serialization
KIND_MAP: dict[type, Literal["user_text", "assistant_text", "tool_call", "function_call_output", "response"]] = {
    UserText: "user_text",
    AssistantText: "assistant_text",
    ToolCall: "tool_call",
    FunctionCallOutput: "function_call_output",
    Response: "response",
}


class JsonlRecord(TypedDict, total=False):
    kind: Literal["user_text", "assistant_text", "tool_call", "function_call_output", "response"]
    # Remaining keys are the event fields (model_dump output)


def to_jsonl_record(evt: EventType) -> JsonlRecord:
    kind = KIND_MAP[type(evt)]
    payload = evt.model_dump(exclude_none=True)
    out: JsonlRecord = {"kind": kind, **payload}
    return out
