from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.llm.mini_codex.mcp_manager import McpManager  # structured MCP snapshot types
from adgn.llm.mini_codex.ui.state import UiState

# --------------------------
# Envelope and core state
# --------------------------


class Envelope(BaseModel):
    """Message envelope: carries protocol metadata and typed payload.
    session: {id: str}, event: {id: int, ts: datetime}, payload: ServerMessage
    """

    session_id: str
    event_id: int
    event_ts: datetime
    payload: ServerMessage
    model_config = ConfigDict(extra="forbid")


class SessionState(BaseModel):
    session_id: str
    version: str
    capabilities: list[str] = []
    last_event_id: int | None = None
    active_run_id: str | None = None
    run_counter: int = 0

    model_config = ConfigDict(extra="forbid")


class ApprovalBrief(BaseModel):
    call_id: str
    tool_key: str
    args: dict = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RunState(BaseModel):
    run_id: str
    status: Literal[
        "idle",
        "starting",
        "running",
        "awaiting_approval",
        "aborting",
        "finished",
        "error",
    ]
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
    result: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class ReasoningChunk(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    text: str

    model_config = ConfigDict(extra="forbid")


class UiMessagePayload(BaseModel):
    mime: Literal["text/markdown"] = "text/markdown"
    content: str
    model_config = ConfigDict(extra="forbid")


class UiMessageEvt(BaseModel):
    type: Literal["ui_message"] = "ui_message"
    message: UiMessagePayload
    model_config = ConfigDict(extra="forbid")


TranscriptItem = Annotated[
    UserText
    | AssistantText
    | ToolCall
    | FunctionCallOutput
    | ReasoningChunk
    | UiMessageEvt,
    Field(discriminator="type"),
]

# --------------------------
# Client -> Server messages
# --------------------------


class Hello(Envelope):
    type: Literal["hello"] = "hello"
    v: str
    client_capabilities: list[str] = []


class Resume(Envelope):
    type: Literal["resume"] = "resume"
    last_seen_event_id: int | None = None


class Send(Envelope):
    type: Literal["send"] = "send"
    text: str
    client_msg_id: str | None = None


class Approve(Envelope):
    type: Literal["approve"] = "approve"
    call_id: str


class Deny(Envelope):
    type: Literal["deny"] = "deny"
    call_id: str


class Abort(Envelope):
    type: Literal["abort"] = "abort"


class GetSnapshot(Envelope):
    type: Literal["get_snapshot"] = "get_snapshot"
    include_transcript_window: bool = False


class Ping(Envelope):
    type: Literal["ping"] = "ping"
    nonce: str | None = None


ClientMessage = Annotated[
    Hello | Resume | Send | Approve | Deny | Abort | GetSnapshot | Ping,
    Field(discriminator="type"),
]

# --------------------------
# Server -> Client messages
# --------------------------


class Welcome(Envelope):
    type: Literal["welcome"] = "welcome"
    v: str
    session_state: SessionState


class McpServerInfo(BaseModel):
    name: str
    model_config = ConfigDict(extra="forbid")


class Snapshot(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    v: str
    session_state: SessionState
    run_state: RunState | None = None
    # Structured MCP state for UI and sampling (Pydantic models from McpManager)
    sampling: McpManager.SamplingSnapshot | None = None
    mcp_servers: list[McpServerInfo] = []
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


ApprovalDecision = Annotated[
    ApprovalApprove | ApprovalDenyContinue | ApprovalDenyAbort,
    Field(discriminator="kind"),
]


class ApprovalDecisionEvt(BaseModel):
    type: Literal["approval_decision"] = "approval_decision"
    call_id: str
    decision: ApprovalDecision
    model_config = ConfigDict(extra="forbid")


class TurnDone(BaseModel):
    type: Literal["turn_done"] = "turn_done"
    model_config = ConfigDict(extra="forbid")


class ErrorCode(str, Enum):
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
    message: str
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
    | UiMessageEvt,
    Field(discriminator="type"),
]
