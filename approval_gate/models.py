"""Data models for the approval gate.

All state variants are discriminated unions — no nullable result fields at the top level.
Invalid states are unrepresentable by construction.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from mcp import types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

# ── The underlying MCP tool call ──────────────────────────────────────────────


class ToolCall(BaseModel):
    """The underlying MCP tool call to forward on approval.

    justification and session_key are stripped before storage here;
    they live on Action directly.
    """

    tool_name: str
    arguments: dict[str, object]

    model_config = ConfigDict(extra="forbid")


# ── Action lifecycle states ───────────────────────────────────────────────────


class ActionStatus(StrEnum):
    pending = "pending"
    executing = "executing"
    done = "done"
    rejected = "rejected"
    withdrawn = "withdrawn"


class PendingState(BaseModel):
    """Awaiting operator decision."""

    status: Literal[ActionStatus.pending] = ActionStatus.pending

    model_config = ConfigDict(extra="forbid")


class ExecutingState(BaseModel):
    """Approved; backend call in flight."""

    status: Literal[ActionStatus.executing] = ActionStatus.executing

    model_config = ConfigDict(extra="forbid")


class DoneState(BaseModel):
    """Backend call completed. outcome.isError distinguishes success from tool error."""

    status: Literal[ActionStatus.done] = ActionStatus.done
    outcome: mcp_types.CallToolResult

    model_config = ConfigDict(extra="forbid")


class RejectedState(BaseModel):
    """Operator rejected the action."""

    status: Literal[ActionStatus.rejected] = ActionStatus.rejected
    reason: str | None = None

    model_config = ConfigDict(extra="forbid")


class WithdrawnState(BaseModel):
    """Agent withdrew the action before it was decided."""

    status: Literal[ActionStatus.withdrawn] = ActionStatus.withdrawn

    model_config = ConfigDict(extra="forbid")


ActionState = Annotated[
    PendingState | ExecutingState | DoneState | RejectedState | WithdrawnState, Field(discriminator="status")
]


# ── Top-level action record ───────────────────────────────────────────────────


class Action(BaseModel):
    """One pending or resolved action record."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    call: ToolCall
    justification: str
    session_key: str | None
    state: ActionState

    model_config = ConfigDict(extra="forbid")


# ── Operator decisions ────────────────────────────────────────────────────────


class ApproveDecision(BaseModel):
    """Operator approved the action; gate will execute it against the backend."""

    kind: Literal["approved"] = "approved"

    model_config = ConfigDict(extra="forbid")


class DenyDecision(BaseModel):
    """Operator denied the action."""

    kind: Literal["denied"] = "denied"
    reason: str | None = None

    model_config = ConfigDict(extra="forbid")


class WithdrawDecision(BaseModel):
    """Agent withdrew the action before a decision was made."""

    kind: Literal["withdrawn"] = "withdrawn"

    model_config = ConfigDict(extra="forbid")


OperatorDecision = Annotated[ApproveDecision | DenyDecision | WithdrawDecision, Field(discriminator="kind")]


# ── Queued-action reference (returned to the agent immediately) ───────────────


class ActionRef(BaseModel):
    """Reference to a queued action, returned immediately when a tool call is submitted.

    The agent should poll resource://actions/{action_id} for the outcome, or subscribe
    to MCP resource-updated notifications to be notified when the state changes.
    """

    action_id: uuid.UUID

    model_config = ConfigDict(extra="forbid")
