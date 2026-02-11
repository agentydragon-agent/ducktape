from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from adgn.agent.server.status_shared import (
    AgentLifecycle,
    AgentStatusCore,
    ContainerState,
    RunPhase,
    UiStateLite,
    build_agent_status_core,
)
from adgn.mcp.snapshots import RunningServerEntry

logger = logging.getLogger(__name__)


# ------------------
# Typed WS messages
# ------------------


class AgentBrief(BaseModel):
    id: str
    live: bool | None = None
    active_run_id: UUID | None = None
    lifecycle: AgentLifecycle | None = None
    model_config = ConfigDict(extra="forbid")


class AgentsSnapshotData(BaseModel):
    agents: list[AgentBrief]
    model_config = ConfigDict(extra="forbid")


class AgentsSnapshotMsg(BaseModel):
    type: Literal["agents_snapshot"] = "agents_snapshot"
    data: AgentsSnapshotData
    model_config = ConfigDict(extra="forbid")


class AgentIdData(BaseModel):
    id: str
    model_config = ConfigDict(extra="forbid")


class AgentCreatedMsg(BaseModel):
    type: Literal["agent_created"] = "agent_created"
    data: AgentIdData
    model_config = ConfigDict(extra="forbid")


class AgentDeletedMsg(BaseModel):
    type: Literal["agent_deleted"] = "agent_deleted"
    data: AgentIdData
    model_config = ConfigDict(extra="forbid")


class AgentStatusData(BaseModel):
    id: str
    live: bool
    active_run_id: UUID | None = None
    lifecycle: AgentLifecycle
    run_phase: RunPhase
    ui: UiStateLite
    container: ContainerState
    last_event_at: str | None = None
    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_core(cls, core: AgentStatusCore) -> AgentStatusData:
        """Build a WS-friendly AgentStatusData from the internal status core.

        Centralizes the mapping and ensures JSON-friendly fields (e.g., last_event_at ISO string).
        Keeps the WS schema stable without exposing internal types directly.
        """
        last = core.last_event_at.isoformat() if core.last_event_at is not None else None
        return cls(
            id=core.id,
            live=core.live,
            active_run_id=core.active_run_id,
            lifecycle=core.lifecycle,
            run_phase=core.run_phase,
            ui=core.ui,
            container=core.container,
            last_event_at=last,
        )


class AgentStatusMsg(BaseModel):
    type: Literal["agent_status"] = "agent_status"
    data: AgentStatusData
    model_config = ConfigDict(extra="forbid")


AgentsHubMsg = Annotated[
    AgentsSnapshotMsg | AgentCreatedMsg | AgentDeletedMsg | AgentStatusMsg, Field(discriminator="type")
]

MSG_ADAPTER: TypeAdapter[AgentsHubMsg] = TypeAdapter(AgentsHubMsg)  # for validation if needed


class AgentsWSHub:
    """Manages general WebSocket connections interested in agent list/status updates."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        # Send initial snapshot of agents with live/status info (typed)
        payload = await self._build_initial_snapshot()
        msg = AgentsSnapshotMsg(data=payload)
        logger.info(
            "agents_ws: sending initial snapshot",
            extra={"connections": len(self._connections), "agents": len(payload.agents)},
        )
        await ws.send_json(msg.model_dump(mode="json"))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self._connections:
            return
        dead: set[WebSocket] = set()
        mtype = message.get("type") if isinstance(message, dict) else None
        logger.info("agents_ws: broadcasting", extra={"connections": len(self._connections), "type": mtype})
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception("agents_ws: send_json failed")
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)

    async def broadcast_agent_created(self, agent_id: str) -> None:
        msg = AgentCreatedMsg(data=AgentIdData(id=agent_id))
        await self.broadcast(msg.model_dump(mode="json"))

    async def broadcast_agent_deleted(self, agent_id: str) -> None:
        msg = AgentDeletedMsg(data=AgentIdData(id=agent_id))
        await self.broadcast(msg.model_dump(mode="json"))

    async def broadcast_agent_status(self, *, agent_id: str, live: bool, active_run_id: UUID | None) -> None:
        data = await self._build_agent_status(agent_id)
        logger.info(
            "agents_ws: agent_status",
            extra={"agent_id": agent_id, "live": live, "active_run_id": str(active_run_id) if active_run_id else None},
        )
        msg = AgentStatusMsg(data=data)
        await self.broadcast(msg.model_dump(mode="json"))

    async def _build_initial_snapshot(self) -> AgentsSnapshotData:
        """Assemble a typed snapshot of all agents including current live/run status."""
        app = self._app
        # Require presence - if not ready, let exceptions propagate
        rows = await app.state.persistence.list_agents()
        out: list[AgentBrief] = []
        for r in rows:
            live_c = app.state.registry.get(r.id)
            active_run = None
            if live_c is not None and live_c.session is not None and live_c.session.active_run:
                active_run = live_c.session.active_run.run_id
            # Derive a lightweight lifecycle: persisted_only | starting | ready
            lifecycle: str | None
            if live_c is None:
                lifecycle = AgentLifecycle.PERSISTED_ONLY
            else:
                lifecycle = AgentLifecycle.STARTING
                # Prefer compositor-backed entries map with typed union members
                entries = await live_c.list_mcp_entries() if live_c is not None else {}
                if (live_c.ui is not None) and (
                    not entries or all(isinstance(e, RunningServerEntry) for e in entries.values())
                ):
                    lifecycle = AgentLifecycle.READY
            out.append(AgentBrief(id=r.id, live=(live_c is not None), active_run_id=active_run, lifecycle=lifecycle))
        return AgentsSnapshotData(agents=out)

    async def _build_agent_status(self, agent_id: str) -> AgentStatusData:
        app = self._app
        core = await build_agent_status_core(app, agent_id)
        return AgentStatusData.from_core(core)


def register_agents_ws(app: FastAPI) -> None:
    """Register the general agents WebSocket endpoint.

    Requires app.state.agents_ws_hub to be initialized by the app factory.
    """
    try:
        # FastAPI app.state is a dynamic namespace; agents_ws_hub is set during app startup
        _ = app.state.agents_ws_hub
    except AttributeError as e:
        raise RuntimeError("agents_ws_hub not initialized; app must set it during startup") from e

    @app.websocket("/ws/agents")
    async def agents_websocket(ws: WebSocket) -> None:
        hub: AgentsWSHub = app.state.agents_ws_hub
        await hub.connect(ws)
        try:
            # Keep alive; allow pings from client
            while True:
                data = await ws.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    logger.debug("agents_ws: ignoring malformed client message: %r", data[:200])
                    continue
                # Validate any client message (optional) via adapter; ignore unrecognized
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            hub.disconnect(ws)
        except Exception:
            logger.exception("agents_ws: connection error")
            hub.disconnect(ws)
            raise
