from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timezone
import json
import logging
from typing import Annotated, Any, Callable, Literal, Type

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from mcp import types as mcp_types
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from adgn.agent.handler import (
    AbortTurnDecision,
    BypassToolInjectOutput,
    ContinueDecision,
)
from adgn.agent.persist import ApprovalOutcome
from adgn.agent.runtime.container import AgentContainer
from adgn.agent.runtime.specs import McpServerSpec
from adgn.agent.server.agents_ws import AgentsWSHub
from adgn.agent.server.protocol import (
    Accepted,
    ApprovalApprove,
    ApprovalBrief,
    ApprovalDecisionEvt,
    ApprovalDenyAbort,
    ApprovalDenyContinue,
    Envelope,
    ErrorCode,
    ErrorEvt,
    UiStateSnapshot,
)


async def _agents_status_broadcast_impl(
    hub: AgentsWSHub, agent_id: str, live: bool, active_run_id: str | None
) -> None:
    await hub.broadcast_agent_status(agent_id=agent_id, live=live, active_run_id=active_run_id)


logger = logging.getLogger(__name__)


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
    type: Literal["set_policy"]
    content: str


class ApplyProposalIn(BaseModel):
    type: Literal["apply_proposal"]
    proposal_id: str
    decision: Literal["approve", "reject"]


class ReconfigureMcpIn(BaseModel):
    type: Literal["reconfigure_mcp"]
    attach: dict[str, dict] | None = None
    detach: list[str] | None = None


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
    | ApplyProposalIn
    | ReconfigureMcpIn,
    Field(discriminator="type"),
]


class WsContext:
    def __init__(self, app: FastAPI, container: AgentContainer):
        self.app = app
        self.container = container
        assert container.ui is not None
        self.cm = container.ui.manager
        self.session = container.session


async def _persist_user_approval(ctx: "WsContext", call_id: str, outcome: ApprovalOutcome) -> None:
    """Record a user approval/deny decision for the active run.

    No-op if there is no active run. Tool key is best-effort from the request cache.
    """
    session = ctx.session
    if session is None or session.active_run is None or session.approval_hub is None:
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
        self._handlers: dict[Type[BaseModel], HandlerFn] = {}

    def on(self, msg_type: Type[BaseModel]):
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
@router.on(GetSnapshotIn)
async def _h_hello_resume_snapshot(ctx: WsContext, _msg: BaseModel) -> None:
    await ctx.cm.send_payload(Accepted())
    # Kick off incremental sampling snapshot streaming without blocking
    asyncio.create_task(ctx.container.sampling_snapshot_incremental())
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
    await ctx.cm.send_payload(
        UiStateSnapshot(v="ui_state_v1", seq=session.ui_state.seq, state=session.ui_state)
    )
    snapshot = session.build_snapshot(sampling=sampling)
    await ctx.cm.send_payload(snapshot)


@router.on(SendIn)
async def _h_send(ctx: WsContext, msg: SendIn) -> None:
    await ctx.cm.send_payload(Accepted())
    if ctx.session is not None:
        await ctx.session.run(msg.text)


@router.on(PingIn)
async def _h_ping(ctx: WsContext, _msg: PingIn) -> None:
    await ctx.cm.send_payload(Accepted())


@router.on(ReconfigureMcpIn)
async def _h_reconfigure_mcp(ctx: WsContext, msg: ReconfigureMcpIn) -> None:
    await ctx.cm.send_payload(Accepted())
    attach_specs: dict[str, McpServerSpec] = {}
    try:
        if msg.attach:
            spec_adapter: TypeAdapter[McpServerSpec] = TypeAdapter(McpServerSpec)
            for name, spec in msg.attach.items():
                # Validate/parse each spec into typed McpServerSpec
                attach_specs[name] = spec_adapter.validate_python(spec)
    except ValidationError:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND))
        return
    try:
        await ctx.container.reconfigure_mcp(attach=attach_specs or {}, detach=msg.detach or [])
    except ValueError as e:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND, message=str(e)))
        return
    except Exception as e:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.AGENT_ERROR, message=str(e)))
        return
    sampling = await ctx.container.sampling_snapshot()
    sess = ctx.session
    if sess is not None:
        await ctx.cm.send_payload(sess.build_snapshot(sampling=sampling))


@router.on(ApproveIn)
async def _h_approve(ctx: WsContext, msg: ApproveIn) -> None:
    session = ctx.session
    if session is None or session.approval_hub is None:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.AGENT_ERROR, message="no session"))
        return
    if msg.call_id not in session.approval_hub._requests:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND))
        return
    session.approval_hub.resolve(msg.call_id, ContinueDecision())
    await ctx.cm.send_payload(ApprovalDecisionEvt(call_id=msg.call_id, decision=ApprovalApprove()))
    await _persist_user_approval(ctx, msg.call_id, ApprovalOutcome.USER_APPROVE)


@router.on(DenyContinueIn)
async def _h_deny_continue(ctx: WsContext, msg: DenyContinueIn) -> None:
    session = ctx.session
    if session is None or session.approval_hub is None:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.AGENT_ERROR, message="no session"))
        return
    if msg.call_id not in session.approval_hub._requests:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND))
        return
    deny_payload = {"ok": False, "error": f"User denied: {msg.call_id}"}
    denial_result = mcp_types.CallToolResult(
        content=[], isError=True, structuredContent=deny_payload
    )
    session.approval_hub.resolve(msg.call_id, BypassToolInjectOutput(result=denial_result))
    await ctx.cm.send_payload(
        ApprovalDecisionEvt(call_id=msg.call_id, decision=ApprovalDenyContinue())
    )
    await _persist_user_approval(ctx, msg.call_id, ApprovalOutcome.USER_DENY_CONTINUE)


@router.on(DenyIn)
async def _h_deny(ctx: WsContext, msg: DenyIn) -> None:
    session = ctx.session
    if session is None or session.approval_hub is None:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.AGENT_ERROR, message="no session"))
        return
    if msg.call_id not in session.approval_hub._requests:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND))
        return
    session.approval_hub.resolve(msg.call_id, AbortTurnDecision(reason="ui_deny"))
    await ctx.cm.send_payload(
        ApprovalDecisionEvt(call_id=msg.call_id, decision=ApprovalDenyAbort())
    )
    await _persist_user_approval(ctx, msg.call_id, ApprovalOutcome.USER_DENY_ABORT)


@router.on(AbortIn)
async def _h_abort(ctx: WsContext, _msg: AbortIn) -> None:
    session = ctx.session
    if session is None:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.AGENT_ERROR, message="no session"))
        return
    if session.active_run is not None:
        await session.cancel_active_run()
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.ABORTING))
    else:
        await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.NOT_RUNNING))


@router.on(SetPolicyIn)
async def _h_set_policy(ctx: WsContext, msg: SetPolicyIn) -> None:
    sess = ctx.session
    if sess and sess.approval_engine:
        if not sess.agent_id:
            await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.AGENT_ERROR, message="no agent"))
            return
        try:
            # Persist first to assign a canonical version, then load into engine
            ver = await ctx.app.state.persistence.set_policy(sess.agent_id, content=msg.content)  # type: ignore[attr-defined]
            sess.approval_engine.load_policy(msg.content, version=ver)
            await ctx.cm.send_payload(Accepted())
        except ValueError:
            await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND))
        await ctx.cm.send_payload(sess.build_snapshot())


@router.on(ApplyProposalIn)
async def _h_apply_proposal(ctx: WsContext, msg: ApplyProposalIn) -> None:
    sess = ctx.session
    if sess and sess.approval_engine:
        try:
            # Apply decision; for approve this validates policy tests via set_policy
            sess.approval_engine.apply(msg.proposal_id, msg.decision)
            if msg.decision == "approve":
                # On approve, persist the new policy version and sync engine version
                if not sess.agent_id:
                    await ctx.cm.send_payload(
                        ErrorEvt(code=ErrorCode.AGENT_ERROR, message="no agent")
                    )
                    return
                content, _ = sess.approval_engine.get_policy()
                # Persist proposal decision
                await ctx.app.state.persistence.set_proposal_status(  # type: ignore[attr-defined]
                    sess.agent_id,
                    proposal_id=msg.proposal_id,
                    status="approved",
                    decided_at=datetime.now(timezone.utc),
                )
                ver = await ctx.app.state.persistence.set_policy(sess.agent_id, content=content)  # type: ignore[attr-defined]
                sess.approval_engine.load_policy(content, version=ver)
            else:
                # Reject: persist decision
                if sess.agent_id:
                    await ctx.app.state.persistence.set_proposal_status(  # type: ignore[attr-defined]
                        sess.agent_id,
                        proposal_id=msg.proposal_id,
                        status="rejected",
                        decided_at=datetime.now(timezone.utc),
                    )
            # On success, ack and push fresh snapshot so UI updates proposals immediately
            await ctx.cm.send_payload(Accepted())
            await ctx.cm.send_payload(sess.build_snapshot())
        except KeyError:
            logger.warning("Proposal not found: %s", msg.proposal_id)
            await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND))
        except ValueError as e:
            # Policy tests failed or invalid outputs; engine marks proposal rejected.
            logger.warning("Policy apply rejected: %s", str(e))
            # Persist rejection to keep DB in sync with engine state
            if sess.agent_id:
                try:
                    await ctx.app.state.persistence.set_proposal_status(  # type: ignore[attr-defined]
                        sess.agent_id,
                        proposal_id=msg.proposal_id,
                        status="rejected",
                        decided_at=datetime.now(timezone.utc),
                    )
                except Exception:
                    logger.debug(
                        "persistence set_proposal_status failed on rejection", exc_info=True
                    )
            await ctx.cm.send_payload(ErrorEvt(code=ErrorCode.INVALID_COMMAND, message=str(e)))


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
            await _ws_send(
                ws, ErrorEvt(code=ErrorCode.AGENT_ERROR, message="agent missing UI facet")
            )
            await ws.close()
            return
        cm = container.ui.manager
        session = container.session

        # Send Accepted only after container is ensured live so callers waiting for
        # Accepted can proceed with a consistent view (e.g., HTTP /api/agents shows live)
        await _ws_send(
            ws,
            Envelope(
                session_id="bootstrap",
                event_id=0,
                event_ts=datetime.now(UTC),
                payload=Accepted(),
            ),
        )

        await cm.connect(ws)
        cm._session = session
        # Broadcast agent live status to general agents hub and bind hub to manager
        hub: AgentsWSHub = app.state.agents_ws_hub  # require hub presence
        active_run_id = session.active_run.run_id if session and session.active_run else None
        asyncio.create_task(
            hub.broadcast_agent_status(
                agent_id=container.agent_id, live=True, active_run_id=active_run_id
            )
        )
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


async def _ws_send(ws: WebSocket, model: BaseModel) -> None:
    """Send a Pydantic model over WS as JSON (model_dump + send_json)."""
    await ws.send_json(model.model_dump(mode="json"))
