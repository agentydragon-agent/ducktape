from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
import json
import logging
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from adgn.agent.persist import ApprovalOutcome
from adgn.agent.runtime.container import AgentContainer
from adgn.agent.server.agents_ws import AgentsWSHub
from adgn.agent.server.protocol import Accepted, ApprovalBrief, Envelope, ErrorCode, ErrorEvt, UiStateSnapshot


async def _agents_status_broadcast_impl(
    hub: AgentsWSHub, agent_id: str, live: bool, active_run_id: UUID | None
) -> None:
    await hub.broadcast_agent_status(agent_id=agent_id, live=live, active_run_id=active_run_id)


logger = logging.getLogger(__name__)


# Pydantic-typed inbound client messages (discriminated union)
class HelloIn(BaseModel):
    type: Literal["hello"]


class ResumeIn(BaseModel):
    type: Literal["resume"]


class PingIn(BaseModel):
    type: Literal["ping"]
    nonce: str | None = None


IncomingMsg = Annotated[HelloIn | ResumeIn | PingIn, Field(discriminator="type")]


class WsContext:
    def __init__(self, app: FastAPI, container: AgentContainer):
        self.app = app
        self.container = container
        assert container.ui is not None
        self.cm = container.ui.manager
        self.session = container.session


async def _persist_user_approval(ctx: WsContext, call_id: str, outcome: ApprovalOutcome) -> None:
    """Record a user approval/deny decision for the active run.

    No-op if there is no active run. Tool key is best-effort from the request cache.
    """
    session = ctx.session
    if session is None or session.active_run is None:
        return
    req = session.approval_hub._requests.get(call_id)
    tool_key = req.tool_key if req else ""
    await ctx.app.state.persistence.record_approval(
        run_id=session.active_run.run_id,
        agent_id=None,
        call_id=call_id,
        tool_key=tool_key,
        outcome=outcome,
        decided_at=datetime.now(UTC),
    )


HandlerFn = Callable[[WsContext, Any], Any]


class WsRouter:
    def __init__(self) -> None:
        self._handlers: dict[type[BaseModel], HandlerFn] = {}

    def on(self, msg_type: type[BaseModel]):
        def _deco(fn: HandlerFn) -> HandlerFn:
            self._handlers[msg_type] = fn
            return fn

        return _deco

    async def dispatch(self, ctx: WsContext, msg: BaseModel) -> None:
        fn = self._handlers.get(type(msg))
        if fn is None:
            await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND))
            return
        res = fn(ctx, msg)
        if asyncio.iscoroutine(res):
            await res


router = WsRouter()


@router.on(HelloIn)
@router.on(ResumeIn)
async def _h_hello_resume_snapshot(ctx: WsContext, _msg: BaseModel) -> None:
    await ctx.cm.send_payload(Accepted())
    # Kick off incremental sampling snapshot streaming without blocking
    task = asyncio.create_task(ctx.container.sampling_snapshot_incremental())
    task.add_done_callback(lambda t: t.exception() if t.done() and not t.cancelled() else None)
    sampling = None
    session = ctx.session
    if session is None:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.AGENT_ERROR, message="no session"))
        return
    if session.active_run:
        session.active_run.pending_approvals = [
            ApprovalBrief(
                call_id=req.tool_call.call_id,
                tool_key=req.tool_key,
                args=json.loads(req.tool_call.args_json or "{}") if req.tool_call.args_json else {},
            )
            for req in session.approval_hub._requests.values()
        ]
    await ctx.cm._emit_ui_bus_messages()
    await ctx.cm.send_payload(UiStateSnapshot(v="ui_state_v1", seq=session.ui_state.seq, state=session.ui_state))
    snapshot = await session.build_snapshot(sampling=sampling)
    await ctx.cm.send_payload(snapshot)


@router.on(PingIn)
async def _h_ping(ctx: WsContext, _msg: PingIn) -> None:
    await ctx.cm.send_payload(Accepted())


def register_ws(app: FastAPI) -> None:
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        # Ensure app startup completed (persistence/registry ready) before handling WS
        await app.state.ready.wait()
        # Accept early so client handshake completes even if container startup takes time
        await ws.accept()
        # Resolve target agent container by agent_id (lazy-start if persisted only)
        agent_id = ws.query_params.get("agent_id")
        # Note: Do not broadcast live status until ensure_live succeeds below
        # Do not implicitly guess agent id from Referer; require explicit query param
        container: AgentContainer | None = None
        if agent_id:
            try:
                container = await app.state.registry.ensure_live(agent_id, with_ui=True)
            except KeyError:
                logger.error("ws: unknown agent id", extra={"agent_id": agent_id})
                await _ws_send(ws, ErrorEvt(code=ErrorCode.NO_AGENT, message="unknown agent"))
                await ws.close()
                return
            except Exception as e:
                logger.exception("ws: ensure_live failed", exc_info=e)
                await _ws_send(ws, ErrorEvt(code=ErrorCode.AGENT_ERROR, message=str(e)))
                await ws.close()
                return
        if container is None:
            logger.error("ws: no container resolved (no agent specified and none live)")
            await _ws_send(ws, ErrorEvt(code=ErrorCode.NO_AGENT, message="no agent specified"))
            await ws.close()
            return

        if not container.ui:
            logger.error("ws: container missing UI facet", extra={"agent_id": container.agent_id})
            await _ws_send(ws, ErrorEvt(code=ErrorCode.AGENT_ERROR, message="agent missing UI facet"))
            await ws.close()
            return
        cm = container.ui.manager
        session = container.session

        # Send Accepted only after container is ensured live so callers waiting for
        # Accepted can proceed with a consistent view (e.g., HTTP /api/agents shows live)
        await _ws_send(ws, Envelope(session_id="bootstrap", event_id=0, event_at=datetime.now(UTC), payload=Accepted()))

        await cm.connect(ws)
        cm._session = session
        # Push a fresh snapshot on connect so late joiners have current state
        if session is not None:
            await cm.send_payload(await session.build_snapshot())
        # Broadcast agent live status to general agents hub and bind hub to manager
        hub: AgentsWSHub = app.state.agents_ws_hub  # require hub presence
        active_run_id = session.active_run.run_id if session and session.active_run else None
        task = asyncio.create_task(
            hub.broadcast_agent_status(agent_id=container.agent_id, live=True, active_run_id=active_run_id)
        )
        task.add_done_callback(lambda t: t.exception() if t.done() and not t.cancelled() else None)
        cm.configure_status_hub(hub, container.agent_id)
        try:
            while True:
                data = await ws.receive_text()
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    await cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_JSON))
                    continue

                try:
                    im: IncomingMsg = TypeAdapter(IncomingMsg).validate_python(obj)
                except ValidationError:
                    await cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND))
                    continue

                ctx = WsContext(app, container)
                await router.dispatch(ctx, im)

        except WebSocketDisconnect:
            try:
                await cm.flush()
            finally:
                await cm.disconnect(ws)
        except Exception:
            # Harden against races where the socket transitions before receive_text accepts
            try:
                await cm.flush()
            finally:
                await cm.disconnect(ws)


async def _ws_send(ws: WebSocket, model: BaseModel) -> None:
    """Send a Pydantic model over WS as JSON (model_dump + send_json)."""
    try:
        await ws.send_json(model.model_dump(mode="json"))
    except Exception:
        # Harden against races when client disconnects during a send. Ignore.
        return
