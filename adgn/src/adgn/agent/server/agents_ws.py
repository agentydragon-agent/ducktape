from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Dict, Literal, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

logger = logging.getLogger(__name__)


# ------------------
# Typed WS messages
# ------------------


class AgentBrief(BaseModel):
    id: str
    live: bool | None = None
    active_run_id: str | None = None
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
    active_run_id: str | None = None
    model_config = ConfigDict(extra="forbid")


class AgentStatusMsg(BaseModel):
    type: Literal["agent_status"] = "agent_status"
    data: AgentStatusData
    model_config = ConfigDict(extra="forbid")


AgentsHubMsg = Annotated[
    AgentsSnapshotMsg | AgentCreatedMsg | AgentDeletedMsg | AgentStatusMsg,
    Field(discriminator="type"),
]

MSG_ADAPTER: TypeAdapter[AgentsHubMsg] = TypeAdapter(AgentsHubMsg)  # for validation if needed


class AgentsWSHub:
    """Manages general WebSocket connections interested in agent list/status updates."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        # Send initial snapshot of agents with live/status info (typed)
        payload = await self._build_initial_snapshot()
        msg = AgentsSnapshotMsg(data=payload)
        await ws.send_json(msg.model_dump(mode="json"))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        if not self._connections:
            return
        dead: Set[WebSocket] = set()
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

    async def broadcast_agent_status(
        self, *, agent_id: str, live: bool, active_run_id: str | None
    ) -> None:
        msg = AgentStatusMsg(
            data=AgentStatusData(id=agent_id, live=live, active_run_id=active_run_id)
        )
        await self.broadcast(msg.model_dump(mode="json"))

    async def _build_initial_snapshot(self) -> AgentsSnapshotData:
        """Assemble a typed snapshot of all agents including current live/run status."""
        app = self._app
        # Require presence – if not ready, let exceptions propagate
        rows = await app.state.persistence.list_agents()
        out: list[AgentBrief] = []
        for r in rows:
            live_c = app.state.registry.get(r.id)
            active_run = None
            if live_c is not None and live_c.session is not None and live_c.session.active_run:
                active_run = live_c.session.active_run.run_id
            out.append(AgentBrief(id=r.id, live=(live_c is not None), active_run_id=active_run))
        return AgentsSnapshotData(agents=out)


def register_agents_ws(app: FastAPI) -> None:
    """Register the general agents WebSocket endpoint and initialize the hub on app.state."""

    if not hasattr(app.state, "agents_ws_hub"):
        app.state.agents_ws_hub = AgentsWSHub(app)

    @app.websocket("/ws/agents")
    async def agents_websocket(ws: WebSocket) -> None:  # noqa: F811 (route name shadow in FastAPI ok)
        hub: AgentsWSHub = app.state.agents_ws_hub
        await hub.connect(ws)
        try:
            # Keep alive; allow pings from client
            while True:
                data = await ws.receive_text()
                try:
                    msg = json.loads(data)
                except Exception:
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
