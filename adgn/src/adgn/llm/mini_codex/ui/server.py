from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Literal as _Lit, cast
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
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
)
from adgn.llm.mini_codex.ui.protocol import (
    Accepted,
    ApprovalApprove,
    ApprovalDecisionEvt,
    ApprovalDenyAbort,
    ApprovalDenyContinue,
    ApprovalPendingEvt,
    AssistantText,
    Envelope,
    ErrorCode,
    ErrorEvt,
    FunctionCallOutput,
    McpServerInfo,
    RunState,
    RunStatusEvt,
    ServerMessage,
    SessionState,
    Snapshot,
    ToolCall,
    UserText,
)

# Minimal local-only FastAPI UI for MiniCodex (v0)
# - Single-session, in-process
# - WebSocket /ws: duplex channel for events and control
# - GET /transcript -> current run transcript
# - GET / -> serves static/index.html from same dir (developer should add static file)

app = FastAPI()
logger = logging.getLogger("mini_codex.ui")
STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
PROTOCOL_VERSION = "1.0.0"


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


# Simple connection manager for one UI client (v0 single-session)
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
                # High-detail log: full envelope payload for test visibility
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

    async def send_payload(self, payload: ServerMessage) -> None:
        evt_id = self._next_event_id()
        envelope = Envelope(
            session_id=self._session_id,
            event_id=evt_id,
            event_ts=datetime.now(UTC),
            payload=payload,
        )
        await self.send_json(envelope.model_dump(mode="json"))

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

    def on_user_text_event(self, evt: Any) -> None:
        self._spawn(self.send_payload(UserText(text=evt.text)))

    async def _send_direct_all(self, payload: dict[str, Any]) -> None:
        for ws, _q, _task in list(self._clients.values()):
            try:
                await ws.send_json(payload)
            except Exception:
                logger.exception("WebSocket direct send failed")
                raise

    def on_assistant_text_event(self, evt: Any) -> None:
        logger.info(
            "manager: assistant_text_event",
            extra={"len": len(getattr(evt, "text", ""))},
        )
        self._spawn(self.send_payload(AssistantText(text=evt.text)))

    def on_tool_call_event(self, evt: Any) -> None:
        self._spawn(
            self.send_payload(
                ToolCall(name=evt.name, args_json=evt.args_json, call_id=evt.call_id)
            )
        )

    async def before_tool_call(self, evt: Any) -> BeforeToolCallDecision:
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
        await self.send_payload(
            ApprovalDecisionEvt(call_id=evt.call_id, decision=proto_dec)
        )
        # Return the handler decision directly to the agent
        return decision

    def on_function_call_output_event(self, evt: Any) -> None:
        self._spawn(
            self.send_payload(
                FunctionCallOutput(call_id=evt.call_id, output=evt.output)
            )
        )


manager = ConnectionManager()


class AgentSession:
    """Single-session orchestrator for MiniCodex UI wiring.

    Runs a real MiniCodex instance; no simulated tool calls in this module.
    """

    def __init__(self) -> None:
        self.transcript: list[dict[str, Any]] = []
        self._task: asyncio.Task | None = None
        self.approval_hub = ApprovalHub()
        self._lock = asyncio.Lock()
        self._active_run_id: str | None = None
        self._agent: MiniCodex | None = None

    def attach_agent(self, agent: MiniCodex) -> None:
        """Attach a MiniCodex instance and register the UI manager as a handler.

        The ConnectionManager implements the handler hooks (on_* and before_tool_call)
        so we register it directly on the agent's controller. We also set the
        manager's session to enable approval hub awaits.
        """
        self._agent = agent
        # Tell manager about this session
        manager.set_session(self)
        # Best-effort: append manager as a handler to the agent so it receives events
        with contextlib.suppress(Exception):
            agent._controller._handlers.append(cast(BaseHandler, manager))

    async def run(self, prompt: str) -> None:
        """Run a single agent turn via the attached MiniCodex instance.

        If no agent is attached, emits an error status to the UI and returns.
        """
        # Guard so only one run at a time
        async with self._lock:
            if self._task is not None and not self._task.done():
                await manager.send_payload(
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
            await manager.send_payload(
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
            try:
                logger.info("agent.run start", extra={"prompt_len": len(prompt)})
                # Track active run id on session for snapshots
                self._active_run_id = run_id
                await self._agent.run(user_text=prompt)
                logger.info("agent.run done")
            except asyncio.CancelledError:
                await manager.send_payload(
                    ErrorEvt(code=ErrorCode.ABORTED, message="aborted")
                )
            except Exception:
                logger.exception("agent.run error")
                await manager.send_payload(
                    ErrorEvt(code=ErrorCode.AGENT_ERROR, message="agent_run_exception")
                )
            finally:
                # Clear active run id and emit finished run_status
                self._active_run_id = None
                # Ensure all previously spawned payloads were sent before emitting finished
                await manager.flush()
                await manager.send_payload(
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
        await manager.send_payload(
            ErrorEvt(code=ErrorCode.NO_AGENT, message="no_agent_attached")
        )
        return


# Single global session for v0
session = AgentSession()


@app.get("/")
async def index() -> FileResponse:
    # Prefer built Svelte app at static/web/index.html; fallback to legacy static/index.html
    primary = STATIC_DIR / "web" / "index.html"
    file_path = primary if primary.exists() else (STATIC_DIR / "index.html")
    if not file_path.exists():
        raise RuntimeError(f"Missing UI file: {file_path}")
    return FileResponse(file_path)


@app.get("/transcript")
async def get_transcript() -> JSONResponse:
    return JSONResponse(session.transcript)


# Pydantic-typed inbound client messages (discriminated union)


class HelloIn(BaseModel):
    type: _Lit["hello"]


class ResumeIn(BaseModel):
    type: _Lit["resume"]


class GetSnapshotIn(BaseModel):
    type: _Lit["get_snapshot"]


class SendIn(BaseModel):
    type: _Lit["send"]
    text: str


class ApproveIn(BaseModel):
    type: _Lit["approve"]
    call_id: str


class DenyIn(BaseModel):
    type: _Lit["deny"]
    call_id: str


class DenyContinueIn(BaseModel):
    type: _Lit["deny_continue"]
    call_id: str


class AbortIn(BaseModel):
    type: _Lit["abort"]


class PingIn(BaseModel):
    type: _Lit["ping"]
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


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        # Skip sending Welcome at handshake: emit nothing, strictly follow the envelope+payload protocol
        while True:
            data = await ws.receive_text()
            try:
                obj = json.loads(data)
            except Exception:
                await manager.send_payload(
                    ErrorEvt(code=ErrorCode.INVALID_JSON, message="invalid_json")
                )
                continue

            im: IncomingMsg = TypeAdapter(IncomingMsg).validate_python(obj)

            match im:
                case HelloIn() | ResumeIn() | GetSnapshotIn():
                    # Build structured list of enabled MCP servers (Pydantic models) and full sampling snapshot
                    agent = session._agent
                    if agent is None:
                        names = []
                        sampling = None
                    else:
                        names = list(agent._mcp.server_names)
                        sampling = await agent._mcp.sampling_snapshot()
                    mcp_servers_list = [McpServerInfo(name=n) for n in names]
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
                            run_state=None,
                            transcript=[],
                            sampling=sampling,
                            mcp_servers=mcp_servers_list,
                        ),
                    )
                    continue

            if isinstance(im, SendIn):
                logger.info("ws: received send", extra={"text_len": len(im.text)})
                await manager.send_payload(Accepted())
                logger.info("ws: sent ack")
                # Only start run if no run is active
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
                        ErrorEvt(code=ErrorCode.NOT_RUNNING, message="no_active_run")
                    )
                continue

            await manager.send_payload(
                ErrorEvt(code=ErrorCode.INVALID_COMMAND, message="unknown_command")
            )

    except WebSocketDisconnect:
        await manager.disconnect(ws)


def run_uvicorn(host: str = "127.0.0.1", port: int = 8765) -> None:
    uvicorn.run(
        "adgn.llm.mini_codex.ui.server:app",
        host=host,
        port=port,
        log_level="info",
    )
