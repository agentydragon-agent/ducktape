"""Typed MiniCodex event types and JSONL mapping (co-located with handlers).

Note: This module hosts the strongly-typed event algebra used by handlers and
loggers. It intentionally avoids enums and base-class discrimination; each
event is a distinct Pydantic model. Transcript serialization adds a `kind`
string derived from the concrete type.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast, overload

from fastmcp.client.client import CallToolResult
from pydantic import BaseModel, Field

from adgn.agent.loop_control import NoLoopDecision
from adgn.openai_utils.model import ReasoningItem


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
class _UserTextRecord(UserText):
    kind: Literal["user_text"] = "user_text"


class _AssistantTextRecord(AssistantText):
    kind: Literal["assistant_text"] = "assistant_text"


class _ToolCallRecord(ToolCall):
    kind: Literal["tool_call"] = "tool_call"


class _ToolCallOutputRecord(ToolCallOutput):
    kind: Literal["function_call_output"] = "function_call_output"


class _ResponseRecord(Response):
    kind: Literal["response"] = "response"


class _ReasoningRecord(ReasoningItem):
    kind: Literal["reasoning"] = "reasoning"


JsonlRecord = Annotated[
    _UserTextRecord
    | _AssistantTextRecord
    | _ToolCallRecord
    | _ToolCallOutputRecord
    | _ResponseRecord
    | _ReasoningRecord,
    Field(discriminator="kind"),
]


_RECORD_CLASS_MAP: dict[type[BaseModel], type[BaseModel]] = {
    UserText: _UserTextRecord,
    AssistantText: _AssistantTextRecord,
    ToolCall: _ToolCallRecord,
    ToolCallOutput: _ToolCallOutputRecord,
    Response: _ResponseRecord,
    ReasoningItem: _ReasoningRecord,
}


@overload
def to_jsonl_record(evt: UserText) -> _UserTextRecord: ...


@overload
def to_jsonl_record(evt: AssistantText) -> _AssistantTextRecord: ...


@overload
def to_jsonl_record(evt: ToolCall) -> _ToolCallRecord: ...


@overload
def to_jsonl_record(evt: ToolCallOutput) -> _ToolCallOutputRecord: ...


@overload
def to_jsonl_record(evt: Response) -> _ResponseRecord: ...


@overload
def to_jsonl_record(evt: ReasoningItem) -> _ReasoningRecord: ...


def to_jsonl_record(evt: EventType) -> JsonlRecord:
    rec_cls = _RECORD_CLASS_MAP[type(evt)]
    data = evt.model_dump(mode="json", exclude_none=True)
    return cast(JsonlRecord, rec_cls(**data))


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
