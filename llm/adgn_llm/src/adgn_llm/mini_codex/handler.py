"""Typed MiniCodex event types and JSONL mapping (co-located with handlers).

Note: This module hosts the strongly-typed event algebra used by handlers and
loggers. It intentionally avoids enums and base-class discrimination; each
event is a distinct Pydantic model. Transcript serialization adds a `kind`
string derived from the concrete type.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Literal, TypedDict, Union
from pydantic import BaseModel
from adgn_llm.mini_codex.loop_control import NoLoopDecision


# ---- Ground-truth usage (OpenAI upstream fields only; no derived numbers) ----
class GroundTruthUsage(BaseModel):
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
    estimation: dict[str, str] | None = None


# ---- Typed events (no shared runtime base required) ----
class UserText(BaseModel):
    text: str


class AssistantText(BaseModel):
    text: str


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any]
    call_id: str


class FunctionCallOutput(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
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


# ---- Transcript JSONL serialization ----
KIND_MAP: dict[
    type,
    Literal["user_text", "assistant_text", "tool_call", "function_call_output", "response"],
] = {
    UserText: "user_text",
    AssistantText: "assistant_text",
    ToolCall: "tool_call",
    FunctionCallOutput: "function_call_output",
    Response: "response",
}


class JsonlRecord(TypedDict, total=False):
    kind: Literal["user_text", "assistant_text", "tool_call", "function_call_output", "response"]
    # All remaining keys are event fields (model_dump output)


def to_jsonl_record(evt: EventType) -> dict[str, Any]:
    kind = KIND_MAP[type(evt)]
    out: dict[str, Any] = {"kind": kind}
    out.update(evt.model_dump(exclude_none=True))
    return out


class BaseHandler:
    """Base handler protocol with no-op implementations (typed-only).

    Implementations must be fast and non-blocking. Exceptions should propagate.
    """

    # Typed hooks (final API)
    def on_response(self, evt: Response) -> None:  # default no-op
        return None

    def on_before_sample(self):  # default: no decision
        return NoLoopDecision()

    def on_user_text_event(self, evt: UserText) -> None:  # default no-op
        return None

    def on_assistant_text_event(self, evt: AssistantText) -> None:  # default no-op
        return None

    def on_tool_call_event(self, evt: ToolCall) -> None:  # default no-op
        return None

    def on_function_call_output_event(self, evt: FunctionCallOutput) -> None:  # default no-op
        return None

    def on_reasoning(self, item: Any) -> None:  # default no-op
        return None
