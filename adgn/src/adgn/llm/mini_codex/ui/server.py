from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from adgn.llm.mini_codex.ui.shared_bus import UiBus, UiMessage
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
        bus = getattr(self._session, "ui_bus", None)
        if bus is None:
            return
        for item in bus.drain_messages():
            if isinstance(item, UiMessage):
                evt = UiMessageEvt(
                    message=UiMessagePayload(mime=item.mime, content=item.content)
                )
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
        await self.send_payload(
            ApprovalPendingEvt(
                call_id=evt.call_id, tool_key=evt.name, args_json=evt.args_json
            )
        )
        if self._session is None:
            return ContinueDecision()
        req = ApprovalRequest(
            tool_key=evt.name,
            tool_call=ApprovalToolCall(
                name=evt.name,
                call_id=evt.call_id,
                args_json=evt.args_json,
            ),
        )
        decision = await self._session.approval_hub.await_decision(evt.call_id, req)
        # Translate handler decision -> protocol-native decision for UI emission
        if isinstance(decision, ContinueDecision):
            proto_dec = ApprovalApprove()
        elif isinstance(decision, AbortTurnDecision):
            proto_dec = ApprovalDenyAbort()
        elif isinstance(decision, BypassToolInjectOutput):
            proto_dec = ApprovalDenyContinue()
        else:
            raise TypeError(
                f"Unknown handler decision type from approval hub: {type(decision).__name__}"
            )
        ade = ApprovalDecisionEvt(call_id=evt.call_id, decision=proto_dec)
        await self._send_and_reduce(ade)
        # Return the handler decision directly to the agent
        return decision

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

    def __init__(self, manager: ConnectionManager) -> None:
        self._task: asyncio.Task | None = None
        self.approval_hub = ApprovalHub()
        self._lock = asyncio.Lock()
        self._active_run_id: str | None = None
        self._active_run_started_at: datetime | None = None
        self._agent: MiniCodex | None = None
        self._manager = manager
        self.ui_bus: UiBus | None = None
        self.ui_state: UiState = new_state()

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
            # Track active run state for snapshot reconnection
            self._active_run_id = run_id
            self._active_run_started_at = started
            try:
                logger.info("agent.run start", extra={"prompt_len": len(prompt)})
                # Track active run id on session for snapshots
                self._active_run_id = run_id
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
                # Clear active run id/state and emit finished run_status
                self._active_run_id = None
                self._active_run_started_at = None
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


IncomingMsg = Annotated[
    HelloIn
    | ResumeIn
    | GetSnapshotIn
    | SendIn
    | ApproveIn
    | DenyContinueIn
    | DenyIn
    | AbortIn
    | PingIn,
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
    session = AgentSession(manager)

    # Store on app.state for external access when needed
    app.state.manager = manager
    app.state.session = session

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
        await manager.connect(ws)
        # Ensure session is wired to the per-agent UI bus if provided by app.state
        ui_bus_obj = getattr(app.state, "ui_bus", None)
        if ui_bus_obj is not None:
            session.ui_bus = ui_bus_obj
        # Wire optional approval policy engine from app.state into this session
        engine = getattr(app.state, "approval_engine", None)
        if engine is not None:
            setattr(session, "approval_engine", engine)
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
                        agent = session._agent
                        if agent is None:
                            names: list[str] = []
                            sampling = None
                        else:
                            names = list(agent._mcp.server_names)
                            sampling = await agent._mcp.sampling_snapshot()
                        mcp_servers_list = [McpServerInfo(name=n) for n in names]
                        # Build run_state snapshot with any in-flight approvals
                        if session._active_run_id is not None:
                            started_at = session._active_run_started_at or datetime.now(
                                UTC
                            )
                            # Convert pending approvals from the approval hub
                            briefs = []
                            for req in session.approval_hub.pending():
                                try:
                                    args = json.loads(req.tool_call.args_json or "{}")
                                except Exception:
                                    args = {}
                                briefs.append(
                                    ApprovalBrief(
                                        call_id=req.tool_call.call_id,
                                        tool_key=req.tool_key,
                                        args=args,
                                    ).model_dump(mode="json")
                                )
                            run_state_snapshot = RunState(
                                run_id=session._active_run_id,
                                status="running",
                                started_at=started_at,
                                finished_at=None,
                                pending_approvals=TypeAdapter(
                                    list[ApprovalBrief]
                                ).validate_python(briefs),
                                last_event_id=manager._event_id or None,
                            )
                        else:
                            run_state_snapshot = None
                        # Drain pending UI messages, then emit UiState snapshot followed by legacy snapshot
                        await manager._emit_ui_bus_messages()
                        await manager.send_payload(
                            UiStateSnapshot(
                                v="ui_state_v1",
                                seq=session.ui_state.seq,
                                state=session.ui_state,
                            )
                        )
                        await manager.send_payload(
                            Snapshot(
                                v=PROTOCOL_VERSION,
                                session_state=SessionState(
                                    session_id=manager._session_id,
                                    version=PROTOCOL_VERSION,
                                    capabilities=[],
                                    last_event_id=manager._event_id or None,
                                    active_run_id=session._active_run_id,
                                    run_counter=0,
                                ),
                                run_state=run_state_snapshot,
                                sampling=sampling,
                                mcp_servers=mcp_servers_list,
                            ),
                        )
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
                    continue

                if isinstance(im, DenyContinueIn):
                    deny_payload = {"ok": False, "error": f"User denied: {im.call_id}"}
                    denial_result = mcp_types.CallToolResult(
                        content=[], isError=True, structuredContent=deny_payload
                    )
                    session.approval_hub.resolve(
                        im.call_id, BypassToolInjectOutput(result=denial_result)
                    )
                    continue

                if isinstance(im, DenyIn):
                    session.approval_hub.resolve(
                        im.call_id, AbortTurnDecision(reason="ui_deny")
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
