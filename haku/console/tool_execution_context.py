"""Per-execution audit context for credential-free in-process MCP servers."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    tool_call_id: str
    operator_id: UUID
    requester: str


current_tool_execution: ContextVar[ToolExecutionContext | None] = ContextVar("current_tool_execution", default=None)


def enter_tool_execution(context: ToolExecutionContext) -> Token[ToolExecutionContext | None]:
    return current_tool_execution.set(context)


def leave_tool_execution(token: Token[ToolExecutionContext | None]) -> None:
    current_tool_execution.reset(token)
