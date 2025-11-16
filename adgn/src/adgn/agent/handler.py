"""Typed MiniCodex event types and JSONL mapping (co-located with handlers).

Note: This module hosts the strongly-typed event algebra used by handlers and
loggers. It intentionally avoids enums and base-class discrimination; each
event is a distinct Pydantic model. Transcript serialization adds a `kind`
string derived from the concrete type.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastmcp.client.client import CallToolResult
from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails
from pydantic import BaseModel

from adgn.agent.loop_control import NoLoopDecision
from adgn.openai_utils.model import ReasoningItem


# ---- Ground-truth usage (OpenAI upstream fields only; no derived numbers) ----
class GroundTruthUsage(BaseModel):
    model: str
    input_tokens: int | None = None
    input_tokens_details: InputTokensDetails | None = None
    output_tokens: int | None = None
    output_tokens_details: OutputTokensDetails | None = None
    total_tokens: int | None = None


# ---- Typed events (no shared runtime base required) ----
class UserText(BaseModel):
    text: str


class AssistantText(BaseModel):
    text: str


class ToolCall(BaseModel):
    name: str
    args_json: str | None = None
    call_id: str


class ToolCallOutput(BaseModel):
    call_id: str
    result: CallToolResult


# ----- Generic before-tool-call decision algebra (handler-level, generic) -----


class ContinueDecision(BaseModel):
    """Proceed with normal execution."""

    action: Literal["continue"] = "continue"


class AbortTurnDecision(BaseModel):
    """Request abort of the entire turn."""

    action: Literal["abort"] = "abort"
    reason: str | None = None


class Response(BaseModel):
    """One OpenAI responses.create result (non-streaming) with usage.

    Emitted once per model call to avoid duplicating usage across assistant/tool events.
    """

    response_id: str | None = None
    usage: GroundTruthUsage
    model: str | None = None
    created_at: datetime | None = None
    idempotency_key: str | None = None


# Union of all current event types (as a typing alias)
type EventType = UserText | AssistantText | ToolCall | ToolCallOutput | Response | ReasoningItem


# ---- Transcript JSONL serialization ----
KIND_MAP: dict[
    type, Literal["user_text", "assistant_text", "tool_call", "function_call_output", "response", "reasoning"]
] = {
    UserText: "user_text",
    AssistantText: "assistant_text",
    ToolCall: "tool_call",
    ToolCallOutput: "function_call_output",
    Response: "response",
    ReasoningItem: "reasoning",
}


type JsonlRecord = dict[str, Any]


def to_jsonl_record(evt: EventType) -> JsonlRecord:
    data = cast(JsonlRecord, evt.model_dump(mode="json", exclude_none=True))
    data["kind"] = KIND_MAP[type(evt)]
    return data


class BaseHandler:
    """Base handler protocol with no-op implementations (typed-only).

    Implementations must be fast and non-blocking. Exceptions should propagate.
    """

    def on_error(self, exc: Exception) -> None:
        """Hook for fatal agent errors. Default: propagate exception (fail-fast)."""
        raise exc

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

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:  # default no-op
        return None

    def on_reasoning(self, item: ReasoningItem) -> None:  # default no-op
        return None
