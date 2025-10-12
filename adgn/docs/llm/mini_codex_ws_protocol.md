# MiniCodex WebSocket Protocol (v1)

Status: draft (intended to replace ad‑hoc v0 events). Server is authoritative for state; clients are thin UIs.

Goals
- Low‑latency duplex channel for running agent turns, streaming text, tool approvals, and aborts
- Server‑authoritative state with resumable clients (refresh/reconnect) via snapshot + replay
- Versioned, schema‑first protocol with strict types (Pydantic on server, TS types in UI)

Versioning
- Protocol version string (semver) is included in the initial Welcome/Hello exchange. This doc defines v1.0.0.

Core concepts
- Session: UI attachments that share the same agent instance, identified by session_id
- Run (turn): a single agent turn (user input → assistant/tool outputs), identified by run_id
- Event log: total ordering (event_id) of server→client events per session, used for resume and replay

Envelope
- All messages are JSON objects with at least these fields:
  - type: string (discriminator)
  - v?: string (protocol version; present on hello/welcome/snapshot; optional on other frames)
  - session_id?: string
  - run_id?: string (UUID)
  - event_id?: integer (monotonic, server→client only)
  - ts?: RFC3339 timestamp
  - req_id?: string (client‑supplied correlation id for command → CommandAccepted/Error)

State models (server authoritative)
- SessionState
  - session_id: str
  - version: str
  - capabilities: list[str]  (e.g., ["reasoning", "approvals", "replay"])
  - last_event_id: int | null
  - active_run_id: UUID | null
  - run_counter: int
- RunState
  - run_id: UUID
  - status: enum("idle", "starting", "running", "awaiting_approval", "aborting", "finished", "error")
  - started_at: datetime
  - finished_at: datetime | null
  - pending_approvals: list[ApprovalBrief]
  - last_event_id: int | null
  - transcript_window: list[TranscriptItem]  (windowed; full transcript retrievable via snapshot)
- ApprovalBrief
  - call_id: str
- tool_key: str  (e.g., "server_tool")
  - args: dict

Transcript items (subset)
- UserText: {type: "user_text", text: str}
- AssistantText: {type: "assistant_text", text: str}
- ToolCall: {type: "tool_call", name: str, args: dict, call_id: str}
- FunctionCallOutput: {type: "function_call_output", call_id: str, result: object}
- ReasoningChunk (optional): {type: "reasoning", text: str}

Client → Server messages (commands)
- Hello
  - {type: "hello", v: "1.0.0", client_capabilities: list[str]}
- Resume
  - {type: "resume", last_seen_event_id: int | null}
- SendUserText
  - {type: "send", text: str, client_msg_id?: str}
- Approve/Deny
  - {type: "approve" | "deny", call_id: str}
- Abort
  - {type: "abort", run_id?: str}
- GetSnapshot
  - {type: "get_snapshot", include_transcript_window?: bool}
- Ping
  - {type: "ping", nonce?: str}

Server → Client messages (events)
- Welcome
  - {type: "welcome", v: "1.0.0", session_state: SessionState}
- Snapshot (for fresh load or resume)
  - {type: "snapshot", v: "1.0.0", session_state: SessionState, run_state: RunState | null, transcript: list[TranscriptItem], event_id: int}
- CommandAccepted (immediate ack)
  - {type: "accepted", req_id?: str}
- RunStatus (status transitions)
  - {type: "run_status", run_state: RunState, event_id}
  - Key statuses: starting, running, awaiting_approval, finished, error, aborting
- Transcript events
  - UserText, AssistantText, ToolCall, FunctionCallOutput, ReasoningChunk (each carries event_id)
- Approvals
  - ApprovalPending {type: "approval_pending", call_id, tool_key, args_json, event_id}
  - ApprovalDecision {type: "approval_decision", call_id, decision: "approve" | "deny_continue" | "deny_abort", event_id}
- TurnDone
  - {type: "turn_done", run_id, event_id}  // emitted when a run completes without tool outputs
- Error
  - {type: "error", code: string, message: string, details?: object}
- Heartbeat
  - {type: "heartbeat", interval_ms: int}
- Backpressure
  - {type: "backpressure", state: "drain" | "ok"}

Semantics
- Ordering: server emits a strictly monotonic event_id; clients may request replay from last_seen_event_id.
- Idempotency: SendUserText may include client_msg_id; duplicate client_msg_id within a run is ignored.
- Multi‑client: server fans out events to all connected clients for a session; approvals are serialized server‑side.
- Run completion: a run is considered complete upon RunStatus.status == "finished"; TurnDone is sent if there were no terminal artifacts (e.g., function_call_output) to ensure UI re‑enable.
- Errors: Invalid commands elicit an Error with code (e.g., INVALID_COMMAND, MISSING_FIELD, STALE_RUN_ID, BUSY) and do not transition state.

Pydantic (Python) — canonical schema
```python
from __future__ import annotations
from typing import Annotated, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID

# Envelope base
class Envelope(BaseModel):
    type: str
    v: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    event_id: int | None = None
    ts: datetime | None = None
    req_id: str | None = None
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

class RunStatusValue(str):
    pass  # use Literal below

class RunState(BaseModel):
    run_id: UUID
    status: Literal[
        "idle", "starting", "running", "awaiting_approval", "aborting", "finished", "error"
    ]
    started_at: datetime
    finished_at: datetime | None = None
    pending_approvals: list[ApprovalBrief] = []
    last_event_id: int | None = None
    model_config = ConfigDict(extra="forbid")

# Transcript items
class UserText(BaseModel):
    type: Literal["user_text"] = "user_text"
    text: str

class AssistantText(BaseModel):
    type: Literal["assistant_text"] = "assistant_text"
    text: str

class ToolCall(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    name: str
    args: dict
    call_id: str

class FunctionCallOutput(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    result: dict  # Serialized MCP CallToolResult (structured + content)

class ReasoningChunk(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    text: str

TranscriptItem = Annotated[
    UserText | AssistantText | ToolCall | FunctionCallOutput | ReasoningChunk,
    Field(discriminator="type"),
]

# Client → Server
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

# Server → Client
class Welcome(Envelope):
    type: Literal["welcome"] = "welcome"
    v: str
    session_state: SessionState

class Snapshot(Envelope):
    type: Literal["snapshot"] = "snapshot"
    v: str
    session_state: SessionState
    run_state: RunState | None = None
    transcript: list[TranscriptItem] = []

class Accepted(Envelope):
    type: Literal["accepted"] = "accepted"

class RunStatusEvt(Envelope):
    type: Literal["run_status"] = "run_status"
    run_state: RunState

class ApprovalPendingEvt(Envelope):
    type: Literal["approval_pending"] = "approval_pending"
    call_id: str
    tool_key: str
    args_json: str | None = None

class ApprovalDecisionEvt(Envelope):
    type: Literal["approval_decision"] = "approval_decision"
    call_id: str
    decision: Literal["approve", "deny_continue", "deny_abort"]

class TurnDone(Envelope):
    type: Literal["turn_done"] = "turn_done"

class ErrorEvt(Envelope):
    type: Literal["error"] = "error"
    code: str
    message: str
    details: dict | None = None

class HeartbeatEvt(Envelope):
    type: Literal["heartbeat"] = "heartbeat"
    interval_ms: int

class BackpressureEvt(Envelope):
    type: Literal["backpressure"] = "backpressure"
    state: Literal["drain", "ok"]

ServerMessage = Annotated[
    Welcome | Snapshot | Accepted | RunStatusEvt | ApprovalPendingEvt |
    ApprovalDecisionEvt | TurnDone | ErrorEvt | HeartbeatEvt | BackpressureEvt |
    # Transcript items are also emitted as server messages
    UserText | AssistantText | ToolCall | FunctionCallOutput | ReasoningChunk,
    Field(discriminator="type"),
]
```

TypeScript types (UI)
```ts
export type RunStatus =
  | "idle" | "starting" | "running" | "awaiting_approval" | "aborting" | "finished" | "error";

export interface SessionState {
  session_id: string;
  version: string;
  capabilities: string[];
  last_event_id?: number | null;
  // UUID string
  active_run_id?: string | null;
  run_counter: number;
}

export interface RunState {
  // UUID string
  run_id: string;
  status: RunStatus;
  started_at: string; // RFC3339
  finished_at?: string | null;
  pending_approvals: ApprovalBrief[];
  last_event_id?: number | null;
}

export interface ApprovalBrief { call_id: string; tool_key: string; args: Record<string, unknown>; }

export type TranscriptItem =
  | { type: "user_text"; text: string }
  | { type: "assistant_text"; text: string }
  | { type: "tool_call"; name: string; args: Record<string, unknown>; call_id: string }
  | { type: "function_call_output"; call_id: string; output: string }
  | { type: "reasoning"; text: string };

// Client → Server
export type ClientMessage =
  | { type: "hello"; v: string; client_capabilities?: string[] }
  | { type: "resume"; last_seen_event_id?: number | null }
  | { type: "send"; text: string; client_msg_id?: string }
  | { type: "approve"; call_id: string }
  | { type: "deny"; call_id: string }
  | { type: "abort"; run_id?: string }
  | { type: "get_snapshot"; include_transcript_window?: boolean }
  | { type: "ping"; nonce?: string };

// Server → Client
export type ServerMessage =
  | { type: "welcome"; v: string; session_state: SessionState }
  | { type: "snapshot"; v: string; session_state: SessionState; run_state?: RunState | null; transcript: TranscriptItem[]; event_id: number }
  | { type: "accepted"; req_id?: string }
  | { type: "run_status"; run_state: RunState; event_id: number }
  | { type: "approval_pending"; call_id: string; tool_key: string; args_json?: string | null; event_id: number }
  | { type: "approval_decision"; call_id: string; decision: "approve" | "deny_continue" | "deny_abort"; event_id: number }
  | { type: "turn_done"; run_id?: string; event_id: number }
  // Note: run_id fields are UUID strings over the wire
  | { type: "error"; code: string; message: string; details?: Record<string, unknown> }
  | { type: "heartbeat"; interval_ms: number }
  | { type: "backpressure"; state: "drain" | "ok" }
  | TranscriptItem & { event_id: number };
```

Handshake & resume
- Client connects → sends hello {v} (or resume with last_seen_event_id)
- Server replies welcome + snapshot (optional) + replay delta from last_seen_event_id (bounded)
- If the gap exceeds server window, server instructs client to fetch full snapshot via get_snapshot

Error codes (non‑exhaustive)
- INVALID_COMMAND / MISSING_FIELD / BAD_ARGUMENT
- STALE_RUN_ID / NOT_RUNNING / BUSY
- UNKNOWN_CALL_ID / APPROVAL_CONFLICT

UI state machine (minimal)
- idle → (accepted/send) → starting → running → awaiting_approval? → finished|error|aborted
- UI flips to idle on run_status.finished or turn_done or aborted

Notes on adoption
- The current ad‑hoc messages (e.g., "status: accepted", "turn_done") can be mapped to their v1 counterparts (Accepted, RunStatus.finished). Start by emitting welcome/snapshot and run_status alongside existing events and migrate the UI to the new types.

Test matrix
- Fresh connect, hello/welcome/snapshot OK
- Send → assistant_text only → run_status.finished (and turn_done for no‑tool runs)
- Tool approval path: approval_pending → approve → function_call_output → finished
- Abort: abort mid‑run → aborted terminal
- Resume after refresh with last_seen_event_id replay
- Multi‑client fanout; de‑dupe idempotent client_msg_id
