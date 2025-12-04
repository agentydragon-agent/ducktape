from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import contextlib
import logging
from typing import Any
import uuid

from adgn.agent.agent import MiniCodex
from adgn.agent.events import AssistantText, Response, ToolCall, ToolCallOutput, UserText
from adgn.agent.handler import BaseHandler
from adgn.agent.persist import Persistence
from adgn.agent.persist.handler import RunPersistenceHandler
from adgn.agent.server.bus import ServerBus, UiEndTurn, UiMessage
from adgn.agent.server.protocol import (
    ApprovalPolicyInfo,
    FunctionCallOutput,
    ProposalInfo,
    ServerMessage,
    SessionState,
    Snapshot,
    ToolCall as UiToolCall,
    UiEndTurnEvt,
    UiMessageEvt,
    UiMessagePayload,
    UserText as UiUserText,
)
from adgn.agent.server.reducer import reduce_ui_state
from adgn.agent.server.state import UiState, new_state
from adgn.agent.server.status_shared import RunPhase, determine_run_phase
from adgn.agent.types import AgentID
from adgn.mcp.approval_policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


class ConnectionManager(BaseHandler):
    """Manages message delivery to UI clients via ServerBus."""

    def __init__(self) -> None:
        self._session: AgentSession | None = None
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._event_id: int = 0
        self._session_id: str = str(uuid.uuid4())

    def _next_event_id(self) -> int:
        self._event_id += 1
        return self._event_id

    async def _send_and_reduce(self, payload: ServerMessage) -> None:
        assert self._session is not None
        await self._session._apply_ui_event(payload)

    async def _emit_ui_bus_messages(self) -> None:
        assert self._session is not None
        if self._session.ui_bus is None:
            return
        bus = self._session.ui_bus
        for item in bus.drain_messages():
            if isinstance(item, UiMessage):
                await self._send_and_reduce(
                    UiMessageEvt(message=UiMessagePayload(mime=item.mime, content=item.content))
                )
            elif isinstance(item, UiEndTurn):
                await self._send_and_reduce(UiEndTurnEvt())

    def set_session(self, session: AgentSession) -> None:
        self._session = session

    def on_response(self, evt: Response) -> None:
        return None

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        t: asyncio.Task[None] = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)

    async def flush(self) -> None:
        if not self._bg_tasks:
            return
        tasks = list(self._bg_tasks)
        await asyncio.gather(*tasks, return_exceptions=True)

    def on_user_text_event(self, evt: UserText) -> None:
        ut = UiUserText(text=evt.text)
        self._spawn(self._send_and_reduce(ut))

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        raise RuntimeError("assistant_text not allowed in UI mode; use ui.send_message tool instead")

    def on_tool_call_event(self, evt: ToolCall) -> None:
        tc = UiToolCall(name=evt.name, args_json=evt.args_json, call_id=evt.call_id)
        self._spawn(self._send_and_reduce(tc))

    # No per-tool interception; Policy Gateway middleware emits approval_pending via notifier

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        # evt.result is already a Pydantic mcp.types.CallToolResult
        fco = FunctionCallOutput(call_id=evt.call_id, result=evt.result)
        self._spawn(self._send_and_reduce(fco))
        self._spawn(self._emit_ui_bus_messages())


class AgentSession:
    def __init__(
        self,
        manager: ConnectionManager,
        *,
        persistence: Persistence,
        agent_id: AgentID,
        approval_engine: PolicyEngine,
        ui_bus: ServerBus | None = None,
    ) -> None:
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._agent: MiniCodex | None = None
        self._manager = manager
        self._persistence: Persistence = persistence
        self.ui_bus: ServerBus | None = ui_bus
        self.ui_state: UiState = new_state()
        self.approval_engine: PolicyEngine = approval_engine
        self._persist_handler: RunPersistenceHandler | None = None
        # Agent identifier for persistence
        self.agent_id: AgentID = agent_id

    def current_run_phase(self) -> RunPhase:
        """Compute the current run phase from live signals (no stored state).

        - IDLE: no pending approvals and no MCP inflight
        - WAITING_APPROVAL / TOOLS_RUNNING: based on live signals

        UI should read pending://calls resource directly for approval state.
        """
        return determine_run_phase(pending_approvals=0, mcp_has_inflight=False)

    async def build_snapshot(self, sampling=None) -> Snapshot:
        # Note: pending_approvals not populated here; UI reads pending://calls resource via MCP

        content, version = self.approval_engine.get_policy()
        # Load proposals from persistence policy store
        proposals = [
            ProposalInfo(id=r.id, status=r.status) for r in await self._persistence.list_policy_proposals(self.agent_id)
        ]
        approval_policy = ApprovalPolicyInfo(content=content, version=version, proposals=proposals)

        return Snapshot(
            session_state=SessionState(
                session_id=self._manager._session_id,
                version="1.0.0",
                capabilities=[],
                last_event_id=self._manager._event_id or None,
            ),
            approval_policy=approval_policy,
            sampling=sampling,
        )

    def attach_agent(self, agent: MiniCodex, *, model: str | None = None, system: str | None = None) -> None:
        self._agent = agent
        self._model = model
        self._system_text = system
        self._manager.set_session(self)

    def set_persist_handler(self, handler: RunPersistenceHandler) -> None:
        self._persist_handler = handler

    async def _apply_ui_event(self, evt: ServerMessage) -> None:
        self.ui_state = reduce_ui_state(self.ui_state, evt)
        # UI state updates now fetched via HTTP GET /api/agents/{id}/snapshot

    async def run(self, prompt: str) -> None:
        async with self._lock:
            if self._task is not None and not self._task.done():
                # Error now returned via HTTP error response, not sent via dead send_payload
                return
            self._task = asyncio.create_task(self._run_impl(prompt))

    async def cancel_active_run(self) -> None:
        """Cancel currently running task (if any) and await its completion."""
        # First, send protocol-level cancellations for any in-flight MCP requests
        if self._agent is not None:
            # Best-effort: synthesize aborted outputs for pending calls; do not
            # attempt to cancel MCP requests via private attributes
            try:
                # Synthesize aborted outputs for any pending tool calls so the
                # Responses API invariant (each function_call has an output) holds.
                # This prevents downstream 400 errors when the SDK validates input.
                self._agent.abort_pending_tool_calls()
            except Exception:
                # Best-effort; do not block abort on synthesis failures
                logger.debug("abort_pending_tool_calls failed", exc_info=True)
        t = self._task
        if t is None or t.done():
            return
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t

    async def _run_impl(self, prompt: str) -> None:
        if self._agent is not None:
            # Agent notices are injected via the NotificationsHandler/ServerModeHandler from MCP resource updates
            try:
                await self._agent.run(user_text=prompt)
            except asyncio.CancelledError:
                # Error now logged, not sent via dead send_payload
                logger.debug("agent_run_cancelled")
            except Exception as e:
                # Error now logged, not sent via dead send_payload
                logger.error(f"agent_run_exception: {e}", exc_info=True)
            finally:
                await self._manager.flush()
                if self._persist_handler is not None:
                    # Ensure all transcript events have been persisted
                    await self._persist_handler.drain()
            return
        # Error now logged, not sent via dead send_payload
        logger.error("no_agent_attached")
        return
