"""MCP channel - MCP server state and sampling snapshots.

Component: RunningInfrastructure.compositor
Availability: Always (compositor always present)
Messages: sampling snapshots, server attach/detach events
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.server.channels.base import ChannelConnectionManager
from adgn.mcp.snapshots import SamplingSnapshot

if TYPE_CHECKING:
    from adgn.mcp.compositor.server import Compositor


# ============================================================================
# Protocol Messages
# ============================================================================


class McpSnapshot(BaseModel):
    """Full MCP state snapshot."""

    type: Literal["mcp_snapshot"] = "mcp_snapshot"
    sampling: SamplingSnapshot
    model_config = ConfigDict(extra="forbid")


class McpServerAttached(BaseModel):
    """MCP server attached event."""

    type: Literal["mcp_server_attached"] = "mcp_server_attached"
    name: str
    model_config = ConfigDict(extra="forbid")


class McpServerDetached(BaseModel):
    """MCP server detached event."""

    type: Literal["mcp_server_detached"] = "mcp_server_detached"
    name: str
    model_config = ConfigDict(extra="forbid")


McpMessage = Annotated[
    McpSnapshot | McpServerAttached | McpServerDetached,
    Field(discriminator="type"),
]


# ============================================================================
# Connection Manager
# ============================================================================


class McpChannelManager(ChannelConnectionManager):
    """Manages WebSocket connections for the MCP channel.

    Broadcasts MCP server state and sampling snapshots to connected clients.
    Always available (compositor is always present in RunningInfrastructure).
    """

    def __init__(self):
        super().__init__("mcp")

    async def send_snapshot(self, compositor: Compositor) -> None:
        """Send current MCP snapshot to all clients."""
        sampling = await compositor.sampling_snapshot()
        snapshot = McpSnapshot(sampling=sampling)
        await self.broadcast(snapshot)


# ============================================================================
# WebSocket Endpoint
# ============================================================================


def register_endpoint(app):
    """Register MCP channel WebSocket endpoint."""
    from fastapi import FastAPI, WebSocket

    from adgn.agent.server.channels.common import handle_channel_ws

    @app.websocket("/ws/mcp")
    async def ws_mcp(ws: WebSocket) -> None:
        """MCP channel - compositor state and sampling snapshots."""
        await handle_channel_ws(
            ws,
            "mcp",
            ws.query_params.get("agent_id"),
            lambda b: b.mcp,
            lambda b, aid: b.mcp.send_snapshot(app.state.registry.get(aid).running.compositor)
            if app.state.registry.get(aid)
            else None,
            app,
        )
