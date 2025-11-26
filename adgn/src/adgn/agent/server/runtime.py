from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import json
import logging
from typing import Any
import uuid

from adgn.agent.agent import MiniCodex
from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine
from adgn.agent.handler import AssistantText, BaseHandler, ToolCall, ToolCallOutput, UserText
from adgn.agent.models.proposal_status import ProposalStatus
from adgn.agent.persist import RunStatus
from adgn.agent.persist.handler import RunPersistenceHandler
from adgn.agent.server.agents_ws import AgentsWSHub
from adgn.agent.server.bus import UiEndTurn, UiMessage
from adgn.agent.server.protocol import (
    ApprovalBrief,
    ApprovalPolicyInfo,
    Envelope,
    ErrorCode,
    ErrorEvt,
    FunctionCallOutput,
    ProposalInfo,
    RunState,
    RunStatus as UiRunStatus,
    RunStatusEvt,
    ServerMessage,
    SessionState,
    Snapshot,
    SnapshotDetails,
    ToolCall as UiToolCall,
    UiEndTurnEvt,
    UiMessageEvt,
    UiMessagePayload,
    UiStateUpdated,
    UserText as UiUserText,
)
from adgn.agent.server.reducer import reduce_ui_state
from adgn.agent.server.state import UiState, new_state
from adgn.agent.server.status_shared import RunPhase, determine_run_phase
from adgn.mcp._shared.calltool import to_pydantic

logger = logging.getLogger(__name__)


class ConnectionManager(BaseHandler):
    """Manages message delivery to UI clients via ServerBus."""

    def __init__(self) -> None:
        self._session: AgentSession | None = None
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._event_id: int = 0
        self._session_id: str = str(uuid.uuid4())
        # Hub binding for status broadcasts (configured by WS layer)
        self._status_hub: AgentsWSHub | None = None
        self._status_agent_id: str | None = None

    def _next_event_id(self) -> int:
        self._event_id += 1
        return self._event_id

    async def _send_and_reduce(self, payload: ServerMessage) -> None:
        await self.send_payload(payload)
        assert self._session is not None
        await self._session._apply_ui_event(payload)
        # Mirror run status changes to agents hub
        if isinstance(payload, RunStatusEvt):
            st = payload.run_state.status
            run_id = payload.run_state.run_id
            active = run_id if st != UiRunStatus.FINISHED else None
            await self.broadcast_status(True, active)

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

    async def send_payload(self, payload: ServerMessage) -> None:
        # Message delivery now handled via other mechanisms (e.g., UI state updates)
        # Mirror run status events to agents hub
        if isinstance(payload, RunStatusEvt):
            st = payload.run_state.status
            run_id = payload.run_state.run_id
            active = run_id if st != UiRunStatus.FINISHED else None
            await self.broadcast_status(True, active)

    def set_session(self, session: AgentSession) -> None:
        self._session = session

    def on_response(self, evt: Any) -> None:
        return None

    def _spawn(self, coro: Any) -> None:
        t: asyncio.Task[Any] = asyncio.create_task(coro)
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
        # FastMCP CallToolResult is not a Pydantic model; project minimal fields
        fco = FunctionCallOutput(call_id=evt.call_id, result=to_pydantic(evt.result))
        self._spawn(self._send_and_reduce(fco))
        self._spawn(self._emit_ui_bus_messages())

    def configure_status_hub(self, hub: AgentsWSHub, agent_id: str) -> None:
        self._status_hub = hub
        self._status_agent_id = agent_id

    async def broadcast_status(self, live: bool, active_run_id) -> None:
        # No-op when not configured (unit tests may use manager without a WS hub)
        if self._status_hub is None or self._status_agent_id is None:
            return
        logger.info(
            "manager: broadcast_status",
            extra={
                "agent_id": self._status_agent_id,
                "live": live,
                "active_run_id": str(active_run_id) if active_run_id else None,
            },
        )
        await self._status_hub.broadcast_agent_status(
            agent_id=self._status_agent_id, live=live, active_run_id=active_run_id
        )


class AgentSession:
    def __init__(
        self,
        manager: ConnectionManager,
        approval_hub: ApprovalHub | None = None,
        *,
        persistence=None,
        agent_id: str | None = None,
        ui_bus: Any | None = None,
        approval_engine: ApprovalPolicyEngine | None = None,
        policy_gateway: Any | None = None,  # PolicyGatewayMiddleware for tracking in-flight calls
    ) -> None:
        self._task: asyncio.Task | None = None
        self.approval_hub = approval_hub or ApprovalHub()
        self._lock = asyncio.Lock()
        self.active_run: RunState | None = None
        self._run_counter = 0
        self._agent: MiniCodex | None = None
        self._manager = manager
        self._persistence = persistence
        self.ui_bus: Any | None = ui_bus
        self.ui_state: UiState = new_state()
        self.approval_engine: ApprovalPolicyEngine | None = approval_engine
        self._persist_handler: RunPersistenceHandler | None = None
        # Optional: agent identifier to associate runs with a specific hosted agent
        self.agent_id: str | None = agent_id
        # No Docker client on session; runtime server handles any containerization
        self._policy_gateway = policy_gateway

    def current_run_phase(self) -> RunPhase:
        """Compute the current run phase from live signals (no stored state).

        - IDLE: no active run
        - WAITING_APPROVAL: there are pending approvals
        - TOOLS_RUNNING: MCP policy gateway has in-flight tool calls
        - SAMPLING: default while running without approvals
        """
        pending = len(self.approval_hub.pending)
        # Check policy gateway for in-flight tool calls (if available)
        has_inflight = bool(self._policy_gateway and self._policy_gateway.has_inflight_calls())
        return determine_run_phase(
            active_run_id=(self.active_run.run_id if self.active_run else None),
            pending_approvals=pending,
            mcp_has_inflight=has_inflight,
        )

    async def build_snapshot(self, sampling=None) -> Snapshot:
        if self.active_run:
            self.active_run.pending_approvals = [
                ApprovalBrief(
                    call_id=req.tool_call.call_id,
                    tool_key=req.tool_key,
                    args=(json.loads(req.tool_call.args_json or "{}") if req.tool_call.args_json else {}),
                )
                for req in self.approval_hub._requests.values()
            ]

        approval_policy = None
        if self.approval_engine is None:
            raise RuntimeError("approval_engine not configured for session")

        content, version = self.approval_engine.get_policy()
        proposals: list[ProposalInfo] = []
        # Load proposals from persistence policy store
        if self._persistence is not None and self.agent_id:
            rows = await self._persistence.list_policy_proposals(self.agent_id)
            for r in rows:
                pid = str(r.id)
                raw = str(r.status)
                # Strict mapping; surface invalid data rather than swallowing
                status = ProposalStatus(raw)
                proposals.append(ProposalInfo(id=pid, status=status))
        approval_policy = ApprovalPolicyInfo(content=content, version=version, proposals=proposals)

        # Build preferred details bundle when all components are present
        details = None
        if (self.active_run is not None) and (sampling is not None) and (approval_policy is not None):
            details = SnapshotDetails(run_state=self.active_run, sampling=sampling, approval_policy=approval_policy)

        return Snapshot(
            v="1.0.0",
            session_state=SessionState(
                session_id=self._manager._session_id,
                version="1.0.0",
                capabilities=[],
                last_event_id=self._manager._event_id or None,
                active_run_id=(self.active_run.run_id if self.active_run else None),
                run_counter=self._run_counter,
            ),
            approval_policy=approval_policy,
            details=details,
        )

    def attach_agent(self, agent: MiniCodex, *, model: str | None = None, system: str | None = None) -> None:
        self._agent = agent
        self._model = model
        self._system_text = system
        self._manager.set_session(self)

    def set_persist_handler(self, handler: RunPersistenceHandler) -> None:
        self._persist_handler = handler

    async def _apply_ui_event(self, evt: Any) -> None:
        self.ui_state = reduce_ui_state(self.ui_state, evt)
        await self._manager.send_payload(UiStateUpdated(v="ui_state_v1", seq=self.ui_state.seq, state=self.ui_state))

    async def run(self, prompt: str) -> None:
        async with self._lock:
            if self._task is not None and not self._task.done():
                await self._manager.send_payload(ErrorEvt(code=ErrorCode.BUSY, message="agent_busy"))
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
            run_id = uuid.uuid4()
            started = datetime.now(UTC)
            model_params: dict[str, Any] = {}
            if self._persistence is None:
                raise RuntimeError("persistence not configured")
            await self._persistence.start_run(
                run_id=run_id,
                agent_id=self.agent_id,
                system_message=self._system_text,
                model=self._model,
                model_params=model_params,
                started_at=started,
            )
            await self._manager.send_payload(
                RunStatusEvt(
                    run_state=RunState(
                        run_id=run_id,
                        status=UiRunStatus.RUNNING,
                        started_at=started,
                        finished_at=None,
                        pending_approvals=[],
                        last_event_id=None,
                    )
                )
            )
            # Mirror live status immediately to agents hub if configured
            await self._manager.broadcast_status(True, run_id)
            # Also push a fresh Snapshot so UIs that rely on snapshot-only
            # state (not incremental run_status) update immediately.
            # This helps early UI elements like the Abort button appear
            # deterministically even if they don't consume run_status events.
            await self._manager.send_payload(await self.build_snapshot())
            self.active_run = RunState(
                run_id=run_id, status=UiRunStatus.RUNNING, started_at=started, pending_approvals=[], last_event_id=None
            )
            self._run_counter += 1
            finish_status = RunStatus.FINISHED
            try:
                await self._agent.run(user_text=prompt)
            except asyncio.CancelledError:
                await self._manager.send_payload(ErrorEvt(code=ErrorCode.ABORTED))
                finish_status = RunStatus.ABORTED
            except Exception as e:
                await self._manager.send_payload(
                    ErrorEvt(code=ErrorCode.AGENT_ERROR, message=f"agent_run_exception: {e}")
                )
                finish_status = RunStatus.ERROR
            finally:
                if self.active_run:
                    self.active_run.status = UiRunStatus.FINISHED
                    self.active_run.finished_at = datetime.now(UTC)
                self.active_run = None
                await self._manager.flush()
                if self._persist_handler is not None:
                    # Ensure all transcript events have been persisted before finishing the run
                    await self._persist_handler.drain()
                await self._persistence.finish_run(run_id=run_id, status=finish_status, finished_at=datetime.now(UTC))
                await self._manager.send_payload(
                    RunStatusEvt(
                        run_state=RunState(
                            run_id=run_id,
                            status=UiRunStatus.FINISHED,
                            started_at=started,
                            finished_at=datetime.now(UTC),
                            pending_approvals=[],
                            last_event_id=None,
                        )
                    )
                )
                # Keep snapshot run_state in sync with finished status
                await self._manager.send_payload(await self.build_snapshot())
                await self._manager.broadcast_status(True, None)
            return
        await self._manager.send_payload(ErrorEvt(code=ErrorCode.NO_AGENT, message="no_agent_attached"))
        return
