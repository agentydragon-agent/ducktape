"""Session channel - agent execution state and transcript.

Component: LocalAgentRuntime.session
Availability: Only when local agent is running
Messages: session state, run state, transcript items (user/assistant/tool)
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.server.channels.base import ChannelConnectionManager
from adgn.agent.types import ToolCall

if TYPE_CHECKING:
    from adgn.agent.server.runtime import AgentSession


# ============================================================================
# Protocol Messages
# ============================================================================


class SessionState(BaseModel):
    """Session metadata."""

    session_id: str
    version: str
    capabilities: list[str] = []
    last_event_id: int | None = None
    active_run_id: UUID | None = None
    run_counter: int = 0
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
    """Run state."""

    run_id: UUID
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    last_event_id: int | None = None
    model_config = ConfigDict(extra="forbid")


class SessionSnapshot(BaseModel):
    """Full session state snapshot."""

    type: Literal["session_snapshot"] = "session_snapshot"
    session_state: SessionState
    run_state: RunState | None = None
    model_config = ConfigDict(extra="forbid")


class UserText(BaseModel):
    """User input text."""

    type: Literal["user_text"] = "user_text"
    text: str
    model_config = ConfigDict(extra="forbid")


class AssistantText(BaseModel):
    """Assistant response text."""

    type: Literal["assistant_text"] = "assistant_text"
    text: str
    model_config = ConfigDict(extra="forbid")


class ToolCallEvt(BaseModel):
    """Tool invocation (wraps canonical ToolCall)."""

    type: Literal["tool_call"] = "tool_call"
    tool_call: ToolCall
    model_config = ConfigDict(extra="forbid")


class ToolResult(BaseModel):
    """Tool execution result."""

    type: Literal["tool_result"] = "tool_result"
    call_id: str
    output: str
    is_error: bool = False
    model_config = ConfigDict(extra="forbid")


class ReasoningChunk(BaseModel):
    """Reasoning token chunk."""

    type: Literal["reasoning"] = "reasoning"
    text: str
    model_config = ConfigDict(extra="forbid")


class RunStatusEvt(BaseModel):
    """Run status change event."""

    type: Literal["run_status"] = "run_status"
    run_state: RunState
    model_config = ConfigDict(extra="forbid")


class TurnDone(BaseModel):
    """Turn completion event."""

    type: Literal["turn_done"] = "turn_done"
    model_config = ConfigDict(extra="forbid")


SessionMessage = Annotated[
    SessionSnapshot | UserText | AssistantText | ToolCallEvt | ToolResult | ReasoningChunk | RunStatusEvt | TurnDone,
    Field(discriminator="type"),
]


# ============================================================================
# Connection Manager
# ============================================================================


class SessionChannelManager(ChannelConnectionManager):
    """Manages WebSocket connections for the session channel.

    Broadcasts session state, run state, and transcript items to connected clients.
    Only available when a local agent is running (LocalAgentRuntime.session exists).
    """

    def __init__(self):
        super().__init__("session")
        self.session: AgentSession | None = None

    async def send_snapshot(self, session: AgentSession) -> None:
        """Send current session snapshot to all clients."""
        snapshot = await self._build_snapshot(session)
        await self.broadcast(snapshot)

    async def _build_snapshot(self, session: AgentSession) -> SessionSnapshot:
        """Build session snapshot from session state."""
        session_state = SessionState(session_id=session._manager._session_id, version="1.0.0", capabilities=[])

        run_state = None
        if session.active_run:
            run_state = RunState(
                run_id=session.active_run.run_id, status=RunStatus.RUNNING, started_at=session.active_run.started_at
            )

        return SessionSnapshot(session_state=session_state, run_state=run_state)


# ============================================================================
# WebSocket Endpoint
# ============================================================================


def register_endpoint(app):
    """Register session channel WebSocket endpoint."""
    from fastapi import WebSocket

    from adgn.agent.server.channels.common import handle_channel_ws

    @app.websocket("/ws/session")
    async def ws_session(ws: WebSocket) -> None:
        """Session channel - agent execution state and transcript."""
        await handle_channel_ws(
            ws,
            "session",
            ws.query_params.get("agent_id"),
            lambda b: b.session,
            lambda b, aid: b.session.send_snapshot(app.state.registry.get(aid).runtime.session)
            if app.state.registry.get(aid) and app.state.registry.get(aid).runtime.session
            else None,
            app,
        )
