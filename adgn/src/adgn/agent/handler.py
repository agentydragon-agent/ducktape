"""Typed MiniCodex event types and JSONL mapping (co-located with handlers).

Note: This module hosts the strongly-typed event algebra used by handlers and
loggers. It intentionally avoids enums and base-class discrimination; each
event is a distinct Pydantic model. Transcript serialization adds a `kind`
string derived from the concrete type.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypeAlias, TypedDict

from mcp import types as mcp_types
from pydantic import BaseModel

from adgn.agent.loop_control import NoLoopDecision
from adgn.openai_utils.model import ReasoningItem

# BeforeToolCallDecision and decision dataclasses are defined below (handler-level, generic)


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
    result: mcp_types.CallToolResult


# ----- Generic before-tool-call decision algebra (handler-level, generic) -----


class ContinueDecision(BaseModel):
    """Proceed with normal execution."""

    action: Literal["continue"] = "continue"


class BypassToolInjectOutput(BaseModel):
    """Bypass MCP execution and inject this tool result into the turn.

    Handlers return this decision to indicate the agent should use the provided
    mcp_types.CallToolResult as the function_call_output for the named call_id
    and must NOT invoke the MCP call for that function.
    """

    result: mcp_types.CallToolResult
    reason: str | None = None
    action: Literal["bypass_inject"] = "bypass_inject"


class AbortTurnDecision(BaseModel):
    """Request abort of the entire turn."""

    action: Literal["abort"] = "abort"
    reason: str | None = None


BeforeToolCallDecision = ContinueDecision | BypassToolInjectOutput | AbortTurnDecision


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
EventType: TypeAlias = (
    UserText | AssistantText | ToolCall | ToolCallOutput | Response | ReasoningItem
)


# ---- Transcript JSONL serialization ----
KIND_MAP: dict[
    type,
    Literal[
        "user_text",
        "assistant_text",
        "tool_call",
        "function_call_output",
        "response",
        "reasoning",
    ],
] = {
    UserText: "user_text",
    AssistantText: "assistant_text",
    ToolCall: "tool_call",
    ToolCallOutput: "function_call_output",
    Response: "response",
    ReasoningItem: "reasoning",
}


class JsonlRecord(TypedDict, total=False):
    kind: Literal[
        "user_text",
        "assistant_text",
        "tool_call",
        "function_call_output",
        "response",
    ]
    # All remaining keys are event fields (model_dump output)


def to_jsonl_record(evt: EventType) -> dict[str, Any]:
    kind = KIND_MAP[type(evt)]
    data = evt.model_dump(mode="json", exclude_none=True)
    data["kind"] = kind
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

    async def before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        """Async hook invoked immediately before executing a tool call.

        The agent does not parse tool arguments. Handlers can inspect evt.args_json
        (opaque JSON string) if needed but should avoid schema assumptions.

        Must return a BeforeToolCallDecision (ContinueDecision | BypassToolInjectOutput | AbortTurnDecision).
        Default implementation returns ContinueDecision() (proceed normally).
        """
        return ContinueDecision()

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:  # default no-op
        return None

    def on_reasoning(self, item: ReasoningItem) -> None:  # default no-op
        return None
