from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import json
import logging
from typing import Any
import uuid

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from adgn.agent.agent import MiniCodex
from adgn.agent.approvals import ApprovalHub, ApprovalPolicyEngine
from adgn.agent.handler import (
    AssistantText,
    BaseHandler,
    BeforeToolCallDecision,
    ContinueDecision,
    ToolCall,
    ToolCallOutput,
    UserText,
)
from adgn.agent.persist import RunStatus
from adgn.agent.persist.handler import RunPersistenceHandler
from adgn.agent.server.agents_ws import AgentsWSHub
from adgn.agent.server.bus import UiEndTurn, UiMessage
from adgn.agent.server.protocol import (
    ApprovalBrief,
    ApprovalPendingEvt,
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
    ToolCall as UiToolCall,
    UiEndTurnEvt,
    UiMessageEvt,
    UiMessagePayload,
    UiStateUpdated,
    UserText as UiUserText,
)
from adgn.agent.server.reducer import reduce_ui_state
from adgn.agent.server.state import UiState, new_state

logger = logging.getLogger(__name__)


class ConnectionManager(BaseHandler):
    def __init__(self) -> None:
        self._clients: dict[int, tuple[WebSocket, asyncio.Queue[Any | None], asyncio.Task]] = {}
        self._session: AgentSession | None = None
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._event_id: int = 0
        self._session_id: str = str(uuid.uuid4())
        # Hub binding for status broadcasts (configured by WS layer)
        self._status_hub: AgentsWSHub | None = None
        self._status_agent_id: str | None = None

    async def connect(self, ws: WebSocket) -> None:
        # Accept only if not already accepted by the route handler
        if ws.application_state is not WebSocketState.CONNECTED:
            await ws.accept()
        q: asyncio.Queue[Any | None] = asyncio.Queue()
        client_id = id(ws)
        task = asyncio.create_task(self._sender_loop(client_id, ws, q))
        self._clients[client_id] = (ws, q, task)

    async def disconnect(self, ws: WebSocket) -> None:
        cid = id(ws)
        conn = self._clients.pop(cid, None)
        if conn:
            _ws, q, task = conn
            # Graceful shutdown: signal sender loop to exit and await task
            q.put_nowait(None)
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except asyncio.TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _sender_loop(
        self, client_id: int, ws: WebSocket, queue: asyncio.Queue[Any | None]
    ) -> None:
        while True:
            payload = await queue.get()
            if payload is None:
                break
            # If the websocket isn't in a connected state, stop sending
            if ws.application_state is not WebSocketState.CONNECTED:
                break
            try:
                logger.info(
                    "manager: sending to client",
                    extra={
                        "client_id": client_id,
                        "kind": payload.get("type") or payload.get("kind"),
                    },
                )
                await ws.send_json(payload)
            except Exception as e:
                logger.warning(
                    "ws send_json failed; disconnecting client",
                    extra={"client_id": client_id, "error": str(e)},
                )
                break

    def _next_event_id(self) -> int:
        self._event_id += 1
        return self._event_id

    async def send_json(self, payload: dict[str, Any]) -> None:
        for _ws, q, _task in list(self._clients.values()):
            q.put_nowait(payload)

    async def _send_and_reduce(self, payload: ServerMessage) -> None:
        await self.send_payload(payload)
        assert self._session is not None
        await self._session._apply_ui_event(payload)
        # Mirror run status changes to agents hub
        if isinstance(payload, RunStatusEvt):
            st = payload.run_state.status
            run_id = payload.run_state.run_id
            active: str | None = run_id if st != UiRunStatus.FINISHED else None
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
        evt_id = self._next_event_id()
        envelope = Envelope(
            session_id=self._session_id,
            event_id=evt_id,
            event_ts=datetime.now(UTC),
            payload=payload,
        )
        env_dict = envelope.model_dump(mode="json")
        await self.send_json(env_dict)
        # Mirror run status events to agents hub
        if isinstance(payload, RunStatusEvt):
            st = payload.run_state.status
            run_id = payload.run_state.run_id
            active: str | None = run_id if st != UiRunStatus.FINISHED else None
            await self.broadcast_status(True, active)

    def set_session(self, session: "AgentSession") -> None:
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

    async def _send_direct_all(self, payload: dict[str, Any]) -> None:
        for ws, _q, _task in list(self._clients.values()):
            await ws.send_json(payload)

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        raise RuntimeError(
            "assistant_text not allowed in UI mode; use ui.send_message tool instead"
        )

    def on_tool_call_event(self, evt: ToolCall) -> None:
        tc = UiToolCall(name=evt.name, args_json=evt.args_json, call_id=evt.call_id)
        self._spawn(self._send_and_reduce(tc))

    async def before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        if self._session is None:
            return ContinueDecision()
        pending_calls = set(self._session.approval_hub._requests.keys())
        if evt.call_id not in pending_calls:
            return ContinueDecision()
        await self.send_payload(
            ApprovalPendingEvt(call_id=evt.call_id, tool_key=evt.name, args_json=evt.args_json)
        )
        return ContinueDecision()

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        payload = evt.result.model_dump(mode="json", exclude_none=True)
        fco = FunctionCallOutput(call_id=evt.call_id, result=payload)
        self._spawn(self._send_and_reduce(fco))
        self._spawn(self._emit_ui_bus_messages())

    def configure_status_hub(self, hub: AgentsWSHub, agent_id: str) -> None:
        self._status_hub = hub
        self._status_agent_id = agent_id

    async def broadcast_status(self, live: bool, active_run_id: str | None) -> None:
        # No-op when not configured (unit tests may use manager without a WS hub)
        if self._status_hub is None or self._status_agent_id is None:
            return
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
    ) -> None:
        self._task: asyncio.Task | None = None
        self.approval_hub = approval_hub or ApprovalHub()
        self._lock = asyncio.Lock()
        self.active_run: RunState | None = None
        self._run_counter = 0
        self._agent: MiniCodex | None = None
        self._manager = manager
        self._persistence = persistence
        self.ui_bus: Any | None = None
        self.ui_state: UiState = new_state()
        self.approval_engine: ApprovalPolicyEngine | None = None
        self._persist_handler: RunPersistenceHandler | None = None
        # Optional: agent identifier to associate runs with a specific hosted agent
        self.agent_id: str | None = None

    def build_snapshot(self, sampling=None) -> Snapshot:
        # mcp_servers list removed; rely on structured sampling snapshot only

        if self.active_run:
            self.active_run.pending_approvals = [
                ApprovalBrief(
                    call_id=req.tool_call.call_id,
                    tool_key=req.tool_key,
                    args=json.loads(req.tool_call.args_json or "{}")
                    if req.tool_call.args_json
                    else {},
                )
                for req in self.approval_hub._requests.values()
            ]

        approval_policy = None
        if self.approval_engine:
            content, version = self.approval_engine.get_policy()
            status = self.approval_engine.get_status()
            proposals: list[ProposalInfo] = []
            for p in status.proposals:
                # Enrich proposal metadata with source for UI diff rendering
                snap = self.approval_engine.get_proposal(p.id)
                proposals.append(
                    ProposalInfo(
                        id=p.id, status=p.status, rationale=p.rationale, source=snap.source
                    )
                )
            approval_policy = ApprovalPolicyInfo(
                content=content, version=version, proposals=proposals
            )

        return Snapshot(
            v="1.0.0",
            session_state=SessionState(
                session_id=self._manager._session_id,
                version="1.0.0",
                capabilities=[],
                last_event_id=self._manager._event_id or None,
                active_run_id=self.active_run.run_id if self.active_run else None,
                run_counter=self._run_counter,
            ),
            run_state=self.active_run,
            sampling=sampling,
            approval_policy=approval_policy,
        )

    def attach_agent(
        self, agent: MiniCodex, *, model: str | None = None, system: str | None = None
    ) -> None:
        self._agent = agent
        self._model = model
        self._system_text = system
        self._manager.set_session(self)

    def set_persist_handler(self, handler: RunPersistenceHandler) -> None:
        self._persist_handler = handler

    async def _apply_ui_event(self, evt: Any) -> None:
        self.ui_state = reduce_ui_state(self.ui_state, evt)
        await self._manager.send_payload(
            UiStateUpdated(v="ui_state_v1", seq=self.ui_state.seq, state=self.ui_state)
        )

    async def run(self, prompt: str) -> None:
        async with self._lock:
            if self._task is not None and not self._task.done():
                await self._manager.send_payload(
                    ErrorEvt(code=ErrorCode.BUSY, message="agent_busy")
                )
                return
            self._task = asyncio.create_task(self._run_impl(prompt))

    async def cancel_active_run(self) -> None:
        """Cancel currently running task (if any) and await its completion."""
        # First, send protocol-level cancellations for any in-flight MCP requests
        if self._agent is not None:
            await self._agent._mcp.cancel_all_outgoing("ui_abort")
            try:
                # Synthesize aborted outputs for any pending tool calls so the
                # Responses API invariant (each function_call has an output) holds.
                # This prevents downstream 400 errors when the SDK validates input.
                if hasattr(self._agent, "abort_pending_tool_calls"):
                    self._agent.abort_pending_tool_calls()
            except Exception:
                # Best-effort; do not block abort on synthesis failures
                logger.debug("abort_pending_tool_calls failed", exc_info=True)
        t = self._task
        if t is None or t.done():
            return
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    async def _run_impl(self, prompt: str) -> None:
        if self._agent is not None:
            run_id = str(uuid.uuid4())
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
                    ),
                )
            )
            # Mirror live status immediately to agents hub if configured
            await self._manager.broadcast_status(True, run_id)
            # Also push a fresh Snapshot so UIs that rely on snapshot-only
            # state (not incremental run_status) update immediately.
            # This helps early UI elements like the Abort button appear
            # deterministically even if they don't consume run_status events.
            await self._manager.send_payload(self.build_snapshot())
            self.active_run = RunState(
                run_id=run_id,
                status=UiRunStatus.RUNNING,
                started_at=started,
                pending_approvals=[],
                last_event_id=None,
            )
            self._run_counter += 1
            finish_status = RunStatus.FINISHED
            try:
                await self._agent.run(user_text=prompt)
            except asyncio.CancelledError:
                await self._manager.send_payload(ErrorEvt(code=ErrorCode.ABORTED))
                finish_status = RunStatus.ABORTED
            except Exception as e:
                # Preserve legacy marker for tests while surfacing details
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
                await self._persistence.finish_run(
                    run_id=run_id, status=finish_status, finished_at=datetime.now(UTC)
                )
                await self._manager.send_payload(
                    RunStatusEvt(
                        run_state=RunState(
                            run_id=run_id,
                            status=UiRunStatus.FINISHED,
                            started_at=started,
                            finished_at=datetime.now(UTC),
                            pending_approvals=[],
                            last_event_id=None,
                        ),
                    ),
                )
                # Keep snapshot run_state in sync with finished status
                await self._manager.send_payload(self.build_snapshot())
                await self._manager.broadcast_status(True, None)
            return
        await self._manager.send_payload(
            ErrorEvt(code=ErrorCode.NO_AGENT, message="no_agent_attached")
        )
        return
