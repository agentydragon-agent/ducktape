from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.presets import AgentPreset, discover_presets
from adgn.agent.runtime.registry import AgentRegistry
from adgn.agent.runtime.specs import McpServerSpec
from adgn.agent.server.agents_ws import register_agents_ws
from adgn.agent.server.ws import register_ws
from adgn.openai_utils.model import OpenAIModelProto

PROTOCOL_VERSION = "1.0.0"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")

logger = logging.getLogger(__name__)


# Request models (module-level to avoid Pydantic forward-ref issues in FastAPI)
class CreateAgentBody(BaseModel):
    preset: str
    system: str | None = None
    metadata: dict[str, Any] | None = None


class PatchAgentMcpBody(BaseModel):
    specs: dict[str, McpServerSpec] | None = None
    attach: dict[str, McpServerSpec] | None = None
    detach: list[str] | None = None


## WebSocket message models moved to ws.py


# Factory to create an isolated app with fresh manager/session


def create_app(
    *,
    require_static_assets: bool = True,
    client_factory: Callable[[str], OpenAIModelProto] | None = None,
) -> FastAPI:
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

    # Optional CORS (for dev cross-origin fetches). Disabled by default.
    # Enable by setting ADGN_UI_CORS_ORIGINS to a comma-separated list or "*".
    cors_env = os.getenv("ADGN_UI_CORS_ORIGINS")
    if cors_env:
        origins = (
            [o.strip() for o in cors_env.split(",") if o.strip()] if cors_env != "*" else ["*"]
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Readiness event so async tests can await startup deterministically
    app.state.ready = asyncio.Event()
    # Wire SQLite persistence at creation; ensure schema during startup
    db_path = os.getenv("ADGN_AGENT_DB_PATH") or str(Path("logs") / "agent.sqlite")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    app.state.persistence = SQLitePersistence(db_path)
    app.state.registry = AgentRegistry(
        persistence=app.state.persistence,
        model=DEFAULT_MODEL,
        client_factory=client_factory,
    )

    # (legacy duplicate) removed; use ConnectionManager._emit_ui_bus_messages

    @app.on_event("startup")
    async def _on_startup() -> None:
        index_path = STATIC_DIR / "index.html"
        logger.info(
            "server startup",
            extra={
                "static_dir": str(STATIC_DIR),
                "index_exists": index_path.exists(),
                "index_path": str(index_path),
            },
        )

        # Ensure persistence schema (generic agent store) — fail startup on error
        await app.state.persistence.ensure_schema()
        logger.info("persistence ready", extra={"db_path": db_path})

        # Multi-agent: agents should be created via API after startup
        app.state.ready.set()

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        """Flush UI events and close all containers via registry actor paths."""
        for container in app.state.registry.list():
            if container.ui:
                await container.ui.manager.flush()
        await app.state.registry.close_all()

    # Note: single-agent fallback removed; agents should be created via API to populate the registry.

    @app.get("/", response_model=None)
    async def index() -> Response:
        # Serve built Svelte app
        file_path = STATIC_DIR / "web" / "index.html"
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

    # -----------------------
    # Agents/Runs API (alpha)
    # -----------------------

    async def _create_live_agent(
        agent_id: str, mcp_specs: dict[str, McpServerSpec], *, system: str | None = None
    ) -> None:
        # Pass typed specs to the registry; McpManager converts at construction
        await app.state.registry.create(agent_id, mcp_specs, with_ui=True, system=system)

    @app.get("/api/agents")
    async def api_list_agents() -> dict[str, Any]:
        rows = await app.state.persistence.list_agents()
        live = {c.agent_id: c for c in app.state.registry.list()}
        working_ids = {
            cid
            for cid, c in live.items()
            if (c.session is not None and c.session.active_run is not None)
        }
        last_map = await app.state.persistence.list_agents_last_activity()
        # Build enriched list and sort by last activity desc (fallback to created_at)
        items: list[tuple[str, datetime, dict[str, Any]]] = []
        for r in rows:
            last_ts = last_map.get(r.id) or r.created_at
            payload = r.model_dump(mode="json")
            payload["live"] = r.id in live
            payload["working"] = r.id in working_ids
            payload["last_updated"] = last_ts.isoformat()
            items.append((r.id, last_ts, payload))
        items.sort(key=lambda t: t[1], reverse=True)
        return {"agents": [p for _, _, p in items]}

    @app.post("/api/agents")
    async def api_create_agent(create: CreateAgentBody = Body(...)) -> dict[str, Any]:
        # Lookup preset; combine with optional override system
        ps = discover_presets(os.getenv("ADGN_AGENT_PRESETS_DIR"))
        p = ps.get(create.preset)
        if p is None:
            return {"error": "unknown_preset"}
        p.typed_specs()
        json_specs = p.specs
        metadata = dict(create.metadata or {})
        metadata["preset"] = create.preset
        # Persist JSON specs and metadata
        agent_id = await app.state.persistence.create_agent(specs=json_specs, metadata=metadata)
        # If preset carries an initial approval policy, persist it before agent start
        if p.approval_policy:
            await app.state.persistence.set_policy(agent_id, content=p.approval_policy)
        # Do not auto-start live container here; it will be lazily started
        # on WebSocket connect via registry.ensure_live().
        # Notify general WS subscribers (hub presence required)
        hub = app.state.agents_ws_hub
        await hub.broadcast_agent_created(agent_id)
        await hub.broadcast_agent_status(agent_id=agent_id, live=False, active_run_id=None)
        return {"id": agent_id}

    @app.delete("/api/agents/{agent_id}")
    async def api_delete_agent(agent_id: str) -> dict[str, Any]:
        # Look up live container and persisted agent row
        container = app.state.registry.get(agent_id)
        row = await app.state.persistence.get_agent(agent_id)
        if container is None and row is None:
            return {"ok": False, "error": "not_found"}
        # If live, close deterministically (cancels run, waits idle, drains persistence)
        if container is not None:
            result = await container.close()
            # Remove closed container from registry regardless of drain outcome
            app.state.registry.remove(agent_id)
            # If drain failed, abort purge and return error
            if not (isinstance(result, dict) and result.get("drained", True)):
                return {"ok": False, "error": "drain_failed"}
        # Always purge persisted records when present
        if row is not None:
            await app.state.persistence.delete_agent(agent_id)
        # Notify general WS subscribers (hub presence required)
        hub = app.state.agents_ws_hub
        await hub.broadcast_agent_status(agent_id=agent_id, live=False, active_run_id=None)
        await hub.broadcast_agent_deleted(agent_id)
        return {"ok": True}

    @app.patch("/api/agents/{agent_id}/mcp")
    async def api_patch_agent_mcp(
        agent_id: str, patch: PatchAgentMcpBody = Body(...)
    ) -> dict[str, Any]:
        # Persist desired state first
        if patch.specs is not None:
            json_specs = {k: v.model_dump(mode="json") for k, v in patch.specs.items()}
            await app.state.persistence.update_agent_specs(agent_id, specs=json_specs)
            persisted_specs = json_specs
        else:
            attach_json = (
                {k: v.model_dump(mode="json") for k, v in patch.attach.items()}
                if patch.attach
                else None
            )
            persisted_specs = await app.state.persistence.patch_agent_specs(
                agent_id, attach=attach_json, detach=patch.detach
            )
        # Apply live changes if container exists
        container = app.state.registry.get(agent_id)
        if container is not None:
            if patch.specs is not None:
                await container.reconfigure_mcp(specs=patch.specs)
            else:
                await container.reconfigure_mcp(attach=patch.attach or {}, detach=patch.detach)
        return {"id": agent_id, "specs": persisted_specs}

    @app.get("/api/agents/{agent_id}")
    async def api_get_agent(agent_id: str) -> dict[str, Any]:
        row = await app.state.persistence.get_agent(agent_id)
        live = app.state.registry.get(agent_id) is not None
        return {"agent": row.model_dump(mode="json") if row else None, "live": live}

    @app.get("/api/agents/{agent_id}/status")
    async def api_agent_status(agent_id: str) -> dict[str, Any]:
        c = app.state.registry.get(agent_id)
        if c is None:
            return {"id": agent_id, "live": False}
        active_run = None
        if c.session and c.session.active_run:
            active_run = c.session.active_run.run_id
        return {"id": agent_id, "live": True, "active_run_id": active_run}

    @app.get("/api/runs")
    async def api_list_runs(agent_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        rows = await app.state.persistence.list_runs(agent_id=agent_id, limit=limit)
        return {"runs": [r.model_dump(mode="json") for r in rows]}

    @app.get("/api/runs/{run_id}")
    async def api_get_run(run_id: str) -> dict[str, Any]:
        row = await app.state.persistence.get_run(run_id)
        return {"run": row.model_dump(mode="json") if row else None}

    @app.get("/api/runs/{run_id}/events")
    async def api_get_run_events(run_id: str) -> dict[str, Any]:
        events = await app.state.persistence.load_events(run_id)
        return {"events": [e.model_dump(mode="json") for e in events]}

    # Note: Historical UiState projection endpoint removed; use WS UiStateSnapshot/UiStateUpdated for live UI.

    # -----------------------
    # Presets API
    # -----------------------

    def _load_presets() -> dict[str, AgentPreset]:
        return discover_presets(os.getenv("ADGN_AGENT_PRESETS_DIR"))

    @app.get("/api/presets")
    async def api_list_presets() -> dict[str, Any]:
        ps = _load_presets()
        items: list[dict[str, Any]] = []
        for name, p in ps.items():
            items.append({"name": name, "description": p.description or None})
        return {"presets": items}

    @app.get("/api/presets/{name}")
    async def api_get_preset(name: str) -> dict[str, Any]:
        ps = _load_presets()
        p = ps.get(name)
        return {"preset": p.model_dump(mode="json") if p else None}

    # Register websocket routes
    register_ws(app)
    register_agents_ws(app)

    return app


def run_uvicorn(host: str = "127.0.0.1", port: int = 8765) -> None:
    uvicorn.run(
        "adgn.agent.server.app:create_app",
        host=host,
        port=port,
        log_level="info",
        factory=True,
    )
