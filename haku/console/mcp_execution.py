"""Trusted execution identity for Console-owned in-process MCP tools.

The application service constructs this identity from authenticated actors and durable ToolCall
state. The dispatcher places it in MCP request metadata only for an in-process transport; a FastMCP
dependency reads and validates that metadata at tool execution. It never appears in tool arguments
or remote MCP traffic, and Console keeps one stable FastMCP server instance where credentials allow.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastmcp import Context
from fastmcp.dependencies import CurrentContext
from pydantic import BaseModel, ConfigDict, Field

_HAKU_EXECUTION_META_KEY = "haku_execution"
_CURRENT_CONTEXT = CurrentContext()


class AgentMcpExecutionCaller(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["agent"] = "agent"
    agent_id: UUID
    # Re-read from the durable Agent immediately before an approved call executes. ``None`` is
    # the migration-safe, fail-closed value for profile-scoped in-process servers.
    access_profile_id: str | None = None


class OperatorMcpExecutionCaller(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["operator"] = "operator"
    operator_id: UUID


type McpExecutionCaller = Annotated[AgentMcpExecutionCaller | OperatorMcpExecutionCaller, Field(discriminator="kind")]


class McpExecutionContext(BaseModel):
    """Explicit caller and approval provenance for one trusted in-process tool execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    caller: McpExecutionCaller
    tool_call_id: str | None
    approving_operator_id: UUID | None = None
    approval_policy_id: str | None = None


def mcp_execution_request_meta(context: McpExecutionContext) -> dict[str, object]:
    """Serialize trusted execution identity into the reserved MCP request metadata field."""

    return {_HAKU_EXECUTION_META_KEY: context.model_dump(mode="json")}


def require_mcp_execution_context(ctx: Context = _CURRENT_CONTEXT) -> McpExecutionContext:
    """FastMCP dependency for Console-owned tools which require authenticated caller identity."""

    request_context = ctx.request_context
    meta = request_context.meta if request_context is not None else None
    raw = getattr(meta, _HAKU_EXECUTION_META_KEY, None) if meta is not None else None
    if raw is None:
        raise RuntimeError("trusted Haku MCP execution context is required")
    return McpExecutionContext.model_validate(raw)
