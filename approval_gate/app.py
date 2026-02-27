"""Combined FastAPI application and server entry point for the approval gate.

Single app served on one port with auth-based routing for /mcp:

    /healthz          — liveness/readiness probe (no auth)
    /api              — Operator REST API (Authentik JWT auth)
    /mcp              — MCP endpoint, accepts either:
                          x-authentik-jwt header → operator (browser frontend)
                          Authorization: Bearer {AGENT_API_KEY} → agent (OpenClaw)
    /static/frontend  — bundled Svelte SPA (JS, CSS, index.html)
    /                 — SPA shell (Authentik JWT auth); uses hash routing (#/actions/{id})

Security is enforced by auth header validation rather than port isolation.
CiliumNetworkPolicy allows both the Authentik outpost and OpenClaw pods to reach
port 8765, but each must present the correct credential for /mcp.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jwt import PyJWKClient
from pydantic import BaseModel

from approval_gate.auth import check_authentik_admin, make_authentik_auth_dep
from approval_gate.config import Settings
from approval_gate.models import Action, ActionStatus, ApproveDecision, DenyDecision
from approval_gate.predicates import load_predicate
from approval_gate.proxy_server import ApprovalGateServer
from approval_gate.storage import ActionStorage

logger = logging.getLogger(__name__)

_FRONTEND_DIST_DIR = Path(__file__).parent / "frontend" / "dist"
_INSTRUCTIONS_TEMPLATE = Path(__file__).parent / "instructions.mako"


class RejectRequest(BaseModel):
    reason: str | None = None


class ActionResponse(BaseModel):
    action: Action


class ActionsListResponse(BaseModel):
    actions: list[Action]


def create_app(settings: Settings, *, include_static: bool = True) -> FastAPI:
    """Build the combined FastAPI app serving UI, REST API, and MCP on a single port.

    include_static=False skips mounting the Svelte SPA (used by export_schema.py
    where the frontend dist directory doesn't exist yet).
    """
    predicate = load_predicate(settings.predicate_path)

    # Single PyJWKClient shared by all routers so JWKS key caching is shared.
    jwks_client = PyJWKClient(settings.operator_jwks_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        storage = await ActionStorage.initialize(settings.db_path)
        gate = ApprovalGateServer(
            backend=settings.backend,
            storage=storage,
            predicate=predicate,
            public_base_url=settings.public_base_url,
            instructions_template_path=str(_INSTRUCTIONS_TEMPLATE),
        )
        # path="/" because FastAPI strips the "/mcp" prefix before forwarding to this sub-app.
        mcp_asgi = gate.http_app(path="/")
        _app.state.storage = storage
        _app.state.gate = gate
        _app.state.mcp_asgi = mcp_asgi

        # Run the MCP ASGI lifespan in a raw asyncio task so its anyio cancel scopes
        # stay within a single task. Using anyio.create_task_group() here would enter
        # the cancel scope in the lifespan's task and exit it in a different task during
        # pytest-asyncio fixture teardown, triggering anyio's cross-task cancel scope
        # guard.
        #
        # We drive the ASGI lifespan protocol manually (send startup/shutdown events,
        # wait for startup.complete) rather than calling mcp_asgi.router.lifespan_context
        # directly. The latter routes through FastAPI's merged_lifespan in some versions
        # and can recursively re-enter the outer app's lifespan, causing a deadlock.
        startup_done = asyncio.Event()
        shutdown_requested = asyncio.Event()

        async def _run_mcp() -> None:
            from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def receive() -> dict[str, Any]:
                return await to_app.get()

            async def send(message: dict[str, Any]) -> None:
                await from_app.put(message)

            scope: dict[str, Any] = {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}, "app": mcp_asgi}

            lifespan_task = asyncio.create_task(mcp_asgi(scope, receive, send), name="mcp-asgi-lifespan")
            try:
                logger.info("[_run_mcp] sending lifespan.startup to MCP ASGI app")
                await to_app.put({"type": "lifespan.startup"})

                # Wait for startup complete/failed, or early task exit.
                startup_waiter: asyncio.Task[dict[str, Any]] = asyncio.create_task(from_app.get())
                done, _ = await asyncio.wait({startup_waiter, lifespan_task}, return_when=asyncio.FIRST_COMPLETED)
                if startup_waiter not in done:
                    startup_waiter.cancel()
                    inner_exc = lifespan_task.exception() if not lifespan_task.cancelled() else asyncio.CancelledError()
                    raise RuntimeError(f"MCP ASGI lifespan exited before startup: {inner_exc!r}")

                msg = startup_waiter.result()
                if msg.get("type") == "lifespan.startup.failed":
                    raise RuntimeError(f"MCP ASGI startup failed: {msg.get('message', '')}")

                logger.info("[_run_mcp] MCP ASGI startup complete, signalling startup_done")
                startup_done.set()
                await shutdown_requested.wait()

                logger.info("[_run_mcp] sending lifespan.shutdown to MCP ASGI app")
                await to_app.put({"type": "lifespan.shutdown"})
                await lifespan_task
            except BaseException as exc:
                logger.error("[_run_mcp] BaseException: %r", exc, exc_info=True)
                if not lifespan_task.done():
                    lifespan_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await lifespan_task
                raise
            finally:
                # Unblock the startup waiter on any failure path.
                startup_done.set()

        task = asyncio.create_task(_run_mcp(), name="run-mcp")
        await startup_done.wait()
        if task.done():
            exc = task.exception()
            if exc is not None:
                raise exc
            raise RuntimeError("MCP lifespan task completed unexpectedly during startup")
        try:
            yield
        finally:
            shutdown_requested.set()
            await task

    app = FastAPI(title="Approval Gate", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    # ── Operator REST API ──────────────────────────────────────────────────────
    _require_auth = make_authentik_auth_dep(jwks_client)
    operator_router = APIRouter(prefix="/api", tags=["operator"], dependencies=[Depends(_require_auth)])

    @operator_router.get("/actions", response_model=ActionsListResponse)
    async def list_actions(
        request: Request, status: ActionStatus | None = None, limit: int = 100
    ) -> ActionsListResponse:
        actions = await request.app.state.storage.list_by_status(status, limit=limit)
        return ActionsListResponse(actions=actions)

    @operator_router.post("/actions/{action_id}/approve", response_model=ActionResponse)
    async def approve_action(request: Request, action_id: str) -> ActionResponse:
        return ActionResponse(action=await request.app.state.gate.decide(action_id, ApproveDecision()))

    @operator_router.post("/actions/{action_id}/reject", response_model=ActionResponse)
    async def reject_action(request: Request, action_id: str, body: RejectRequest | None = None) -> ActionResponse:
        reason = body.reason if body else None
        return ActionResponse(action=await request.app.state.gate.decide(action_id, DenyDecision(reason=reason)))

    app.include_router(operator_router)

    # ── Unified MCP ASGI — accepts JWT (operator browser) or Bearer (agent) ──
    # Requests with x-authentik-jwt are validated as Authentik admin JWT.
    # Requests with Authorization: Bearer {AGENT_API_KEY} are accepted as agent.
    # All other requests receive 401.
    async def unified_mcp_asgi(
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[MutableMapping[str, Any]]],
        send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            jwt_token = headers.get(b"x-authentik-jwt", b"").decode()
            auth_header = headers.get(b"authorization", b"").decode()
            if jwt_token:
                try:
                    await check_authentik_admin(jwks_client, jwt_token)
                except HTTPException as exc:
                    response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
                    await response(scope, receive, send)
                    return
            elif auth_header == f"Bearer {settings.agent_api_key}":
                pass  # agent auth OK
            else:
                response = JSONResponse({"detail": "Authentication required"}, status_code=401)
                await response(scope, receive, send)
                return
        await app.state.mcp_asgi(scope, receive, send)

    app.mount("/mcp", unified_mcp_asgi)

    if include_static:
        # Serve bundled Svelte SPA (JS, CSS, index.html) under /static/frontend/
        app.mount("/static/frontend", StaticFiles(directory=str(_FRONTEND_DIST_DIR)), name="frontend")

        _html = (_FRONTEND_DIST_DIR / "index.html").read_text()

        # Single SPA shell — hash routing (#/actions/{id}) keeps all navigation client-side.
        # No auth here: index.html contains no secrets; the SPA's API calls enforce auth.
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def _index() -> HTMLResponse:
            return HTMLResponse(_html)

    return app


async def _serve() -> None:
    settings = Settings.load()
    app = create_app(settings)
    logger.info("serving on %s:%d", settings.host, settings.port)
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info"))
    await server.serve()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
