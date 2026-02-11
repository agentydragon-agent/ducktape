from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from mcp import types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.models.policy_error import PolicyTestsSummary
from adgn.agent.models.proposal_status import ProposalStatus
from adgn.agent.server.bus import MimeType
from adgn.agent.server.state import UiState
from adgn.mcp.snapshots import SamplingSnapshot  # structured snapshot model (module-level)

# --------------------------
# Envelope and core state
# --------------------------


class Envelope(BaseModel):
    """Message envelope: carries protocol metadata and typed payload.
    session: {id: str}, event: {id: int, ts: datetime}, payload: ServerMessage
    """

    session_id: str
    event_id: int
    event_at: datetime
    payload: ServerMessage
    model_config = ConfigDict(extra="forbid")


class SessionState(BaseModel):
    session_id: str
    version: str
    capabilities: list[str] = []
    last_event_id: int | None = None
    active_run_id: UUID | None = None
    run_counter: int = 0

    model_config = ConfigDict(extra="forbid")


class ApprovalBrief(BaseModel):
    call_id: str
    tool_key: str
    args: dict = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


## Tests summary/error model shared in adgn.agent.models.policy_error


class ProposalInfo(BaseModel):
    """Policy proposal information for UI (no policy content included)."""

    id: str
    status: ProposalStatus
    # Optional docstring extracted from class ApprovalPolicy
    docstring: str | None = None
    # Optional structured test results summary
    tests: PolicyTestsSummary | None = None

    model_config = ConfigDict(extra="forbid")


class ApprovalPolicyInfo(BaseModel):
    """Current approval policy state."""

    content: str
    version: int
    proposals: list[ProposalInfo] = []

    model_config = ConfigDict(extra="forbid")


class RunStatus(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    ABORTING = "aborting"
    FINISHED = "finished"
    ERROR = "error"


class RunState(BaseModel):
    run_id: UUID
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    pending_approvals: list[ApprovalBrief] = []
    last_event_id: int | None = None

    model_config = ConfigDict(extra="forbid")


# --------------------------
# Transcript items
# --------------------------


class UserText(BaseModel):
    type: Literal["user_text"] = "user_text"
    text: str

    model_config = ConfigDict(extra="forbid")


class AssistantText(BaseModel):
    type: Literal["assistant_text"] = "assistant_text"
    text: str

    model_config = ConfigDict(extra="forbid")


class ToolCall(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    name: str
    args_json: str | None = None
    call_id: str

    model_config = ConfigDict(extra="forbid")


class FunctionCallOutput(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    # Carry full Pydantic MCP CallToolResult; wire serialization handled by Pydantic
    result: mcp_types.CallToolResult

    model_config = ConfigDict(extra="forbid")


class ReasoningChunk(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    text: str

    model_config = ConfigDict(extra="forbid")


class UiMessagePayload(BaseModel):
    mime: MimeType = MimeType.MARKDOWN
    content: str
    model_config = ConfigDict(extra="forbid")


class UiMessageEvt(BaseModel):
    type: Literal["ui_message"] = "ui_message"
    message: UiMessagePayload
    model_config = ConfigDict(extra="forbid")


class UiEndTurnEvt(BaseModel):
    type: Literal["ui_end_turn"] = "ui_end_turn"
    model_config = ConfigDict(extra="forbid")


TranscriptItem = Annotated[
    UserText | AssistantText | ToolCall | FunctionCallOutput | ReasoningChunk | UiMessageEvt | UiEndTurnEvt,
    Field(discriminator="type"),
]

## Client -> Server message types are no longer used; REST handles mutations.

# --------------------------
# Server -> Client messages
# --------------------------


class Welcome(Envelope):
    type: Literal["welcome"] = "welcome"
    v: str
    session_state: SessionState


class SnapshotDetails(BaseModel):
    """Non-nullable bundle of snapshot details.

    Group formerly individually-optional fields into a single optional bundle.
    This reduces surprising nullability at the protocol boundary.
    """

    run_state: RunState
    sampling: SamplingSnapshot
    approval_policy: ApprovalPolicyInfo

    model_config = ConfigDict(extra="forbid")


class Snapshot(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    v: str
    session_state: SessionState
    approval_policy: ApprovalPolicyInfo | None = None
    # Preferred: a single optional bundle; each item inside is non-nullable
    details: SnapshotDetails | None = None
    model_config = ConfigDict(extra="forbid")


# New: server-owned UiState messages
class UiStateSnapshot(BaseModel):
    type: Literal["ui_state_snapshot"] = "ui_state_snapshot"
    v: Literal["ui_state_v1"] = "ui_state_v1"
    seq: int
    state: UiState
    model_config = ConfigDict(extra="forbid")


class UiStateUpdated(BaseModel):
    type: Literal["ui_state_updated"] = "ui_state_updated"
    v: Literal["ui_state_v1"] = "ui_state_v1"
    seq: int
    state: UiState
    model_config = ConfigDict(extra="forbid")


class Accepted(BaseModel):
    type: Literal["accepted"] = "accepted"
    model_config = ConfigDict(extra="forbid")


class RunStatusEvt(BaseModel):
    type: Literal["run_status"] = "run_status"
    run_state: RunState
    model_config = ConfigDict(extra="forbid")


class ApprovalPendingEvt(BaseModel):
    type: Literal["approval_pending"] = "approval_pending"
    call_id: str
    tool_key: str
    args_json: str | None = None
    model_config = ConfigDict(extra="forbid")


# Approval decisions are protocol-native (distinct from handler actions)
class ApprovalApprove(BaseModel):
    kind: Literal["approve"] = "approve"
    model_config = ConfigDict(extra="forbid")


class ApprovalDenyContinue(BaseModel):
    kind: Literal["deny_continue"] = "deny_continue"
    model_config = ConfigDict(extra="forbid")


class ApprovalDenyAbort(BaseModel):
    kind: Literal["deny_abort"] = "deny_abort"
    model_config = ConfigDict(extra="forbid")


ApprovalDecision = Annotated[ApprovalApprove | ApprovalDenyContinue | ApprovalDenyAbort, Field(discriminator="kind")]


class ApprovalDecisionEvt(BaseModel):
    type: Literal["approval_decision"] = "approval_decision"
    call_id: str
    decision: ApprovalDecision
    model_config = ConfigDict(extra="forbid")


class TurnDone(BaseModel):
    type: Literal["turn_done"] = "turn_done"
    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    INVALID_JSON = "INVALID_JSON"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_COMMAND = "INVALID_COMMAND"
    BUSY = "BUSY"
    ABORTING = "ABORTING"
    NOT_RUNNING = "NOT_RUNNING"
    NO_AGENT = "NO_AGENT"
    AGENT_ERROR = "AGENT_ERROR"
    ABORTED = "ABORTED"


class ErrorEvt(BaseModel):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str | None = None
    details: dict | None = None
    model_config = ConfigDict(extra="forbid")


class HeartbeatEvt(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    interval_ms: int
    model_config = ConfigDict(extra="forbid")


class BackpressureEvt(BaseModel):
    type: Literal["backpressure"] = "backpressure"
    state: Literal["drain", "ok"]
    model_config = ConfigDict(extra="forbid")


ServerMessage = Annotated[
    Accepted
    | RunStatusEvt
    | ApprovalPendingEvt
    | ApprovalDecisionEvt
    | TurnDone
    | ErrorEvt
    | HeartbeatEvt
    | BackpressureEvt
    | Snapshot
    | UiStateSnapshot
    | UiStateUpdated
    | UserText
    | AssistantText
    | ToolCall
    | FunctionCallOutput
    | ReasoningChunk
    | UiMessageEvt
    | UiEndTurnEvt,
    Field(discriminator="type"),
]
