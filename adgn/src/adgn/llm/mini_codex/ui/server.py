from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from adgn.llm.mini_codex.ui.shared_bus import UiBus, UiMessage, UiEndTurn
import uuid

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp import types as mcp_types
from pydantic import BaseModel, Field, TypeAdapter
import uvicorn

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.approvals import (
    ApprovalHub,
    ApprovalPolicyEngine,
    ApprovalRequest,
    ApprovalToolCall,
)
from adgn.llm.mini_codex.handler import (
    AbortTurnDecision,
    BaseHandler,
    BeforeToolCallDecision,
    BypassToolInjectOutput,
    ContinueDecision,
    ToolCall,
    ToolCallOutput,
    UserText,
    AssistantText,
)
from adgn.llm.mini_codex.ui.protocol import (
    Accepted,
    ApprovalApprove,
    ApprovalBrief,
    ApprovalDecisionEvt,
    ApprovalDenyAbort,
    ApprovalDenyContinue,
    ApprovalPendingEvt,
    ApprovalPolicyInfo,
    ProposalInfo,
    Envelope,
    ErrorCode,
    ErrorEvt,
    McpServerInfo,
    RunState,
    RunStatusEvt,
    ServerMessage,
    SessionState,
    Snapshot,
    ToolCall as UiToolCall,
    FunctionCallOutput as UiFunctionCallOutput,
    UiMessageEvt,
    UiMessagePayload,
    UiEndTurnEvt,
    UiStateSnapshot,
    UiStateUpdated,
    UserText as UiUserText,
)
from adgn.llm.mini_codex.ui.state import UiState, new_state
from adgn.llm.mini_codex.ui.reducer import reduce_ui_state


PROTOCOL_VERSION = "1.0.0"

logger = logging.getLogger("mini_codex.ui")


class ConnectionManager(BaseHandler):
    def __init__(self) -> None:
        self._clients: dict[
            int, tuple[WebSocket, asyncio.Queue[dict[str, Any]], asyncio.Task]
        ] = {}
        self._session: AgentSession | None = None
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._event_id: int = 0
        self._session_id: str = str(uuid.uuid4())

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        client_id = id(ws)
        task = asyncio.create_task(self._sender_loop(client_id, ws, q))
        self._clients[client_id] = (ws, q, task)

    async def disconnect(self, ws: WebSocket) -> None:
        cid = id(ws)
        conn = self._clients.pop(cid, None)
        if conn:
            _ws, _q, task = conn
            task.cancel()
            with contextlib.suppress(Exception):
                await task

    async def _sender_loop(
        self, client_id: int, ws: WebSocket, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        while True:
            payload = await queue.get()
            try:
                logger.info(
                    "manager: sending to client",
                    extra={
                        "client_id": client_id,
                        "kind": payload.get("type") or payload.get("kind"),
                    },
                )
                logger.warning("WS OUT: %s", json.dumps(payload))
                await ws.send_json(payload)
            except Exception:
                logger.exception("WebSocket send_json failed")
                raise

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

    async def _emit_ui_bus_messages(self) -> None:
        # Drain per-agent UI bus (if any) and emit UiMessageEvt in order, reducing into UiState
        assert self._session is not None
        if self._session.ui_bus is None:
            return
        bus = self._session.ui_bus
        for item in bus.drain_messages():
            if isinstance(item, UiMessage):
                evt = UiMessageEvt(
                    message=UiMessagePayload(mime=item.mime, content=item.content)
                )
                await self._send_and_reduce(evt)
            elif isinstance(item, UiEndTurn):
                evt = UiEndTurnEvt()
                await self._send_and_reduce(evt)

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

    # ---- Handler adapter methods (so manager can be used as a BaseHandler) ----
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

    async def _send_direct_all(self, payload: dict[str, Any]) -> None:
        for ws, _q, _task in list(self._clients.values()):
            try:
                await ws.send_json(payload)
            except Exception:
                logger.exception("WebSocket direct send failed")
                raise

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        # UI mode contract: assistant must not emit plain text.
        # Agents should call ui.send_message (MCP) which becomes UiMessageEvt/AssistantMarkdown.
        raise RuntimeError(
            "assistant_text not allowed in UI mode; use ui.send_message tool instead"
        )

    def on_tool_call_event(self, evt: ToolCall) -> None:
        tc = UiToolCall(name=evt.name, args_json=evt.args_json, call_id=evt.call_id)
        self._spawn(self._send_and_reduce(tc))

    async def before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        # Only handle UI communication for approvals that are actually pending
        # ApprovalPolicyHandler has already evaluated the policy and registered with hub if needed
        if self._session is None:
            return ContinueDecision()

        # Check if this call is actually pending approval
        # Access the approval hub's internal requests directly
        pending_calls = set(self._session.approval_hub._requests.keys())
        if evt.call_id not in pending_calls:
            # Not pending - policy already decided (probably "allow")
            return ContinueDecision()

        # This call is pending approval - send UI event and let ApprovalPolicyHandler handle the decision
        await self.send_payload(
            ApprovalPendingEvt(
                call_id=evt.call_id, tool_key=evt.name, args_json=evt.args_json
            )
        )

        # Don't call await_decision() here - ApprovalPolicyHandler is already waiting
        # Just pass through and let the approval flow continue normally
        return ContinueDecision()

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        payload = evt.result.model_dump(mode="json", exclude_none=True)
        fco = UiFunctionCallOutput(call_id=evt.call_id, result=payload)
        self._spawn(self._send_and_reduce(fco))
        # Drain UI messages right after the tool result to preserve order
        self._spawn(self._emit_ui_bus_messages())


class AgentSession:
    """Single-session orchestrator for MiniCodex UI wiring.

    Runs a real MiniCodex instance; no simulated tool calls in this module.
    """

    def __init__(self, manager: ConnectionManager, approval_hub: ApprovalHub | None = None) -> None:
        self._task: asyncio.Task | None = None
        self.approval_hub = approval_hub or ApprovalHub()
        self._lock = asyncio.Lock()
        # Unified run state
        self.active_run: RunState | None = None
        self._run_counter = 0
        self._agent: MiniCodex | None = None
        self._manager = manager
        self.ui_bus: UiBus | None = None
        self.ui_state: UiState = new_state()
        self.approval_engine: ApprovalPolicyEngine | None = None

    def build_snapshot(self, sampling=None) -> Snapshot:
        """Build a complete snapshot with all current state.

        Note: sampling must be passed in separately as it requires async.
        """
        # Get MCP servers from agent if available
        mcp_servers_list = []
        if self._agent is not None:
            servers = self._agent._mcp.server_names
            mcp_servers_list = [McpServerInfo(name=s) for s in servers]

        # Update run state with pending approvals if active
        if self.active_run:
            self.active_run.pending_approvals = [
                ApprovalBrief(
                    call_id=req.tool_call.call_id,
                    tool_key=req.tool_key,
                    args=json.loads(req.tool_call.args_json or "{}"),
                    )
                    for req in self.approval_hub._requests.values()
                ]

        # Get approval policy if available
        approval_policy = None
        if self.approval_engine:
            content, version = self.approval_engine.get_policy()
            status = self.approval_engine.get_status()
            proposals = [
                ProposalInfo(
                    id=p.id,
                    status=p.status,
                    rationale=p.rationale,
                    source=p.source
                )
                for p in status.proposals
            ]
            approval_policy = ApprovalPolicyInfo(
                content=content, version=version, proposals=proposals
            )

        return Snapshot(
            v=PROTOCOL_VERSION,
            session_state=SessionState(
                session_id=self._manager._session_id,
                version=PROTOCOL_VERSION,
                capabilities=[],
                last_event_id=self._manager._event_id or None,
                active_run_id=self.active_run.run_id if self.active_run else None,
                run_counter=self._run_counter,
            ),
            run_state=self.active_run,
            sampling=sampling,
            mcp_servers=mcp_servers_list,
            approval_policy=approval_policy,
        )

    def attach_agent(self, agent: MiniCodex) -> None:
        """Attach a MiniCodex instance and register the UI manager as a handler.

        The ConnectionManager implements the handler hooks (on_* and before_tool_call)
        so we register it directly on the agent's controller. We also set the
        manager's session to enable approval hub awaits.
        """
        self._agent = agent
        # Tell manager about this session
        self._manager.set_session(self)
        # Best-effort: append manager as a handler to the agent so it receives events
        with contextlib.suppress(Exception):
            agent._controller._handlers.append(cast(BaseHandler, self._manager))

    async def _apply_ui_event(self, evt: Any) -> None:
        # Reduce UiState and broadcast an update
        self.ui_state = reduce_ui_state(self.ui_state, evt)
        await self._manager.send_payload(
            UiStateUpdated(v="ui_state_v1", seq=self.ui_state.seq, state=self.ui_state)
        )

    async def run(self, prompt: str) -> None:
        """Run a single agent turn via the attached MiniCodex instance.

        If no agent is attached, emits an error status to the UI and returns.
        """
        # Guard so only one run at a time
        async with self._lock:
            if self._task is not None and not self._task.done():
                await self._manager.send_payload(
                    ErrorEvt(code=ErrorCode.BUSY, message="agent_busy")
                )
                return
            self._task = asyncio.create_task(self._run_impl(prompt))

    async def _run_impl(self, prompt: str) -> None:
        # If a real agent is attached, run it and forward events via registered handlers
        if self._agent is not None:
            # Emit run_status: starting/running
            run_id = str(uuid.uuid4())
            started = datetime.now(UTC)
            await self._manager.send_payload(
                RunStatusEvt(
                    run_state=RunState(
                        run_id=run_id,
                        status="running",
                        started_at=started,
                        finished_at=None,
                        pending_approvals=[],
                        last_event_id=None,
                    ),
                ),
            )
            # Track active run state
            self.active_run = RunState(
                run_id=run_id,
                status="running",
                started_at=started,
                pending_approvals=[],
                last_event_id=None,
            )
            self._run_counter += 1
            try:
                logger.info("agent.run start", extra={"prompt_len": len(prompt)})
                await self._agent.run(user_text=prompt)
                logger.info("agent.run done")
            except asyncio.CancelledError:
                await self._manager.send_payload(
                    ErrorEvt(code=ErrorCode.ABORTED, message="aborted")
                )
            except Exception:
                logger.exception("agent.run error")
                await self._manager.send_payload(
                    ErrorEvt(code=ErrorCode.AGENT_ERROR, message="agent_run_exception")
                )
            finally:
                # Update run state to finished
                if self.active_run:
                    self.active_run.status = "finished"
                    self.active_run.finished_at = datetime.now(UTC)
                self.active_run = None
                # Ensure all previously spawned payloads were sent before emitting finished
                await self._manager.flush()
                await self._manager.send_payload(
                    RunStatusEvt(
                        run_state=RunState(
                            run_id=run_id,
                            status="finished",
                            started_at=started,
                            finished_at=datetime.now(UTC),
                            pending_approvals=[],
                            last_event_id=None,
                        ),
                    ),
                )
            return

        # No agent attached; report error and return
        await self._manager.send_payload(
            ErrorEvt(code=ErrorCode.NO_AGENT, message="no_agent_attached")
        )
        return


# Pydantic-typed inbound client messages (discriminated union)
class HelloIn(BaseModel):
    type: Literal["hello"]


class ResumeIn(BaseModel):
    type: Literal["resume"]


class GetSnapshotIn(BaseModel):
    type: Literal["get_snapshot"]


class SendIn(BaseModel):
    type: Literal["send"]
    text: str


class ApproveIn(BaseModel):
    type: Literal["approve"]
    call_id: str


class DenyIn(BaseModel):
    type: Literal["deny"]
    call_id: str


class DenyContinueIn(BaseModel):
    type: Literal["deny_continue"]
    call_id: str


class AbortIn(BaseModel):
    type: Literal["abort"]


class PingIn(BaseModel):
    type: Literal["ping"]
    nonce: str | None = None


class SetPolicyIn(BaseModel):
    """User directly sets the approval policy (privileged operation)."""
    type: Literal["set_policy"]
    content: str


class ApplyProposalIn(BaseModel):
    """User approves or rejects a policy proposal (privileged operation)."""
    type: Literal["apply_proposal"]
    proposal_id: str
    decision: Literal["approve", "reject"]


IncomingMsg = Annotated[
    HelloIn
    | ResumeIn
    | GetSnapshotIn
    | SendIn
    | ApproveIn
    | DenyContinueIn
    | DenyIn
    | AbortIn
    | PingIn
    | SetPolicyIn
    | ApplyProposalIn,
    Field(discriminator="type"),
]


# Factory to create an isolated app with fresh manager/session


def create_app(*, require_static_assets: bool = True) -> FastAPI:
    app = FastAPI()
    STATIC_DIR = Path(__file__).with_name("static")

    def _mount_static(path: str, directory: Path, name: str) -> None:
        if not directory.exists():
            if require_static_assets:
                raise RuntimeError(
                    f"Static directory missing: {directory}. Build MiniCodex UI assets before running."
                )
            logger.warning(
                "Skipping mount for missing static directory",
                extra={"path": path, "directory": str(directory)},
            )
            return
        app.mount(path, StaticFiles(directory=directory, check_dir=True), name=name)

    _mount_static("/static", STATIC_DIR, "static")
    _mount_static("/assets", STATIC_DIR / "web" / "assets", "assets")

    # Readiness event so async tests can await startup deterministically
    app.state.ready = asyncio.Event()

    # (legacy duplicate) removed; use ConnectionManager._emit_ui_bus_messages

    @app.on_event("startup")
    async def _on_startup() -> None:
        index_path = STATIC_DIR / "index.html"
        logger.info(
            "ui startup",
            extra={
                "static_dir": str(STATIC_DIR),
                "index_exists": index_path.exists(),
                "index_path": str(index_path),
            },
        )

        # Create session with approval_hub from app.state if available
        approval_hub = getattr(app.state, "approval_hub", None)
        session = AgentSession(manager, approval_hub=approval_hub)
        app.state.session = session

        # If a factory to build/attach the agent was provided, run it on this loop
        attach = getattr(app.state, "agent_factory", None)
        if attach is not None:
            try:
                agent = await attach()
                session.attach_agent(agent)
                logger.info("agent attached on startup")
            except Exception:
                logger.exception("agent attach on startup failed")
        app.state.ready.set()

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        """Gracefully stop inner agent/MCP when server exits (dev/serve)."""
        inner_agent = getattr(app.state, "_inner_agent", None)
        inner_mcp = getattr(app.state, "_inner_mcp", None)
        # Flush any queued UI events
        try:
            await manager.flush()
        except Exception:
            logger.exception("manager.flush on shutdown failed")
        # Close agent first (it may reference MCP), then MCP
        try:
            if inner_agent is not None and hasattr(inner_agent, "__aexit__"):
                await inner_agent.__aexit__(None, None, None)
        except Exception:
            logger.exception("agent __aexit__ on shutdown failed")
        try:
            if inner_mcp is not None and hasattr(inner_mcp, "__aexit__"):
                await inner_mcp.__aexit__(None, None, None)
        except Exception:
            logger.exception("mcp __aexit__ on shutdown failed")

    manager = ConnectionManager()

    # Store manager on app.state for external access when needed
    app.state.manager = manager
    # Note: session will be created during startup with proper approval_hub

    @app.get("/", response_model=None)
    async def index() -> Response:
        # Prefer built Svelte app at static/web/index.html; fallback to legacy static/index.html
        primary = STATIC_DIR / "web" / "index.html"
        file_path = primary if primary.exists() else (STATIC_DIR / "index.html")
        if not file_path.exists():
            if require_static_assets:
                raise RuntimeError(f"Missing UI file: {file_path}")
            return Response(
                content="MiniCodex UI assets not built",
                media_type="text/plain",
                status_code=200,
            )
        return FileResponse(file_path)

    @app.get("/vite.svg", response_model=None)
    async def vite_svg() -> Response:
        svg = STATIC_DIR / "web" / "vite.svg"
        if not svg.exists():
            svg = STATIC_DIR / "vite.svg"
        if not svg.exists():
            if require_static_assets:
                raise RuntimeError("Missing vite.svg asset")
            return Response(content="", media_type="image/svg+xml", status_code=404)
        return FileResponse(svg)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        # Get the session created during startup
        session = getattr(app.state, "session")

        await manager.connect(ws)
        # Wire the session to the manager so it can access it for UI operations
        manager._session = session
        # Ensure session is wired to the per-agent UI bus if provided by app.state
        ui_bus_obj = getattr(app.state, "ui_bus", None)
        if ui_bus_obj is not None:
            session.ui_bus = ui_bus_obj
        # Wire optional approval policy engine from app.state into this session
        session.approval_engine = getattr(app.state, "approval_engine", None)
        # Ack connection so clients can verify liveness immediately
        await manager.send_payload(Accepted())
        try:
            while True:
                data = await ws.receive_text()
                try:
                    obj = json.loads(data)
                except Exception:
                    await manager.send_payload(
                        ErrorEvt(code=ErrorCode.INVALID_JSON, message="invalid_json")
                    )
                    continue

                try:
                    im: IncomingMsg = TypeAdapter(IncomingMsg).validate_python(obj)
                except Exception:
                    await manager.send_payload(
                        ErrorEvt(
                            code=ErrorCode.INVALID_COMMAND, message="invalid_message"
                        )
                    )
                    continue

                match im:
                    case HelloIn() | ResumeIn() | GetSnapshotIn():
                        await manager.send_payload(Accepted())

                        # Get async sampling data if agent available
                        sampling = None
                        if session._agent is not None:
                            sampling = await session._agent._mcp.sampling_snapshot()

                        # Update run state with current pending approvals if active
                        if session.active_run:
                            session.active_run.pending_approvals = [
                                ApprovalBrief(
                                    call_id=req.tool_call.call_id,
                                    tool_key=req.tool_key,
                                    args=json.loads(req.tool_call.args_json or "{}") if req.tool_call.args_json else {}
                                )
                                for req in session.approval_hub._requests.values()
                            ]
                        # Drain pending UI messages, then emit UiState snapshot followed by legacy snapshot
                        await manager._emit_ui_bus_messages()
                        await manager.send_payload(
                            UiStateSnapshot(
                                v="ui_state_v1",
                                seq=session.ui_state.seq,
                                state=session.ui_state,
                            )
                        )
                        # Build and send complete snapshot
                        snapshot = session.build_snapshot(sampling=sampling)
                        await manager.send_payload(snapshot)
                        continue

                if isinstance(im, SendIn):
                    logger.info("ws: received send", extra={"text_len": len(im.text)})
                    await manager.send_payload(Accepted())
                    logger.info("ws: sent ack")
                    await session.run(im.text)
                    logger.info("ws: dispatched session.run")
                    continue

                if isinstance(im, ApproveIn):
                    session.approval_hub.resolve(im.call_id, ContinueDecision())
                    # Send approval decision event to UI
                    await manager.send_payload(
                        ApprovalDecisionEvt(call_id=im.call_id, decision=ApprovalApprove())
                    )
                    continue

                if isinstance(im, DenyContinueIn):
                    deny_payload = {"ok": False, "error": f"User denied: {im.call_id}"}
                    denial_result = mcp_types.CallToolResult(
                        content=[], isError=True, structuredContent=deny_payload
                    )
                    session.approval_hub.resolve(
                        im.call_id, BypassToolInjectOutput(result=denial_result)
                    )
                    # Send approval decision event to UI
                    await manager.send_payload(
                        ApprovalDecisionEvt(call_id=im.call_id, decision=ApprovalDenyContinue())
                    )
                    continue

                if isinstance(im, DenyIn):
                    session.approval_hub.resolve(
                        im.call_id, AbortTurnDecision(reason="ui_deny")
                    )
                    # Send approval decision event to UI
                    await manager.send_payload(
                        ApprovalDecisionEvt(call_id=im.call_id, decision=ApprovalDenyAbort())
                    )
                    continue

                if isinstance(im, AbortIn):
                    if session._task is not None and not session._task.done():
                        session._task.cancel()
                        await manager.send_payload(
                            ErrorEvt(code=ErrorCode.ABORTING, message="aborting")
                        )
                    else:
                        await manager.send_payload(
                            ErrorEvt(
                                code=ErrorCode.NOT_RUNNING, message="no_active_run"
                            )
                        )
                    continue

                if isinstance(im, SetPolicyIn):
                    # User directly sets the approval policy
                    if session.approval_engine:
                        try:
                            session.approval_engine.set_policy(im.content)
                            await manager.send_payload(Accepted())
                        except ValueError as e:
                            await manager.send_payload(
                                ErrorEvt(code=ErrorCode.INVALID_COMMAND, message=f"Invalid policy: {e}")
                            )
                        # Send updated snapshot with new policy
                        await manager.send_payload(session.build_snapshot())
                    continue

                if isinstance(im, ApplyProposalIn):
                    # User approves or rejects a proposal
                    if session.approval_engine:
                        try:
                            session.approval_engine.apply(im.proposal_id, im.decision)
                            await manager.send_payload(Accepted())
                            # Send updated snapshot with new policy if approved
                            if im.decision == "approve":
                                await manager.send_payload(session.build_snapshot())
                        except KeyError as e:
                            logger.warning(f"Proposal not found: {e}")
                            await manager.send_payload(
                                ErrorEvt(code=ErrorCode.INVALID_COMMAND, message=f"Proposal not found: {im.proposal_id}")
                            )
                    continue

                await manager.send_payload(
                    ErrorEvt(code=ErrorCode.INVALID_COMMAND, message="unknown_command")
                )

        except WebSocketDisconnect:
            await manager.disconnect(ws)

    return app


def run_uvicorn(host: str = "127.0.0.1", port: int = 8765) -> None:
    uvicorn.run(
        "adgn.llm.mini_codex.ui.server:create_app",
        host=host,
        port=port,
        log_level="info",
        factory=True,
    )
