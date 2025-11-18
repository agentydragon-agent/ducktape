"""WebSocket endpoints for modular channels."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from adgn.agent.server.channels.bundle import ChannelBundle
from adgn.agent.server.channels.common import Accepted, ChannelEnvelope, ErrorCode, ErrorEvt

logger = logging.getLogger(__name__)


async def _send(ws: WebSocket, payload: dict) -> None:
    """Send JSON message over WebSocket, ignoring errors."""
    try:
        await ws.send_json(payload)
    except Exception:
        # Client disconnected, ignore
        pass


async def _send_error(ws: WebSocket, channel: str, code: ErrorCode, message: str | None = None) -> None:
    """Send error envelope to client."""
    envelope = ChannelEnvelope(
        channel=channel,
        event_id=0,
        event_at=datetime.now(UTC),
        payload=ErrorEvt(code=code, message=message),
    )
    await _send(ws, envelope.model_dump(mode="json"))


async def _send_accepted(ws: WebSocket, channel: str) -> None:
    """Send accepted envelope to client."""
    envelope = ChannelEnvelope(
        channel=channel,
        event_id=0,
        event_at=datetime.now(UTC),
        payload=Accepted(),
    )
    await _send(ws, envelope.model_dump(mode="json"))


def register_channel_endpoints(app: FastAPI) -> None:
    """Register all channel WebSocket endpoints."""

    async def _get_channel_bundle(agent_id: str) -> ChannelBundle | None:
        """Get or create channel bundle for agent."""
        await app.state.ready.wait()
        try:
            runtime = await app.state.registry.ensure_live(agent_id, with_ui=True)
        except KeyError:
            return None
        except Exception as e:
            logger.exception("ensure_live failed", exc_info=e)
            return None

        # Get or create channel bundle
        if runtime._channel_bundle is None:
            runtime._channel_bundle = ChannelBundle.for_agent_runtime(runtime)
        return runtime._channel_bundle

    @app.websocket("/ws/mcp")
    async def ws_mcp(ws: WebSocket) -> None:
        """MCP channel - compositor state and sampling snapshots."""
        agent_id = ws.query_params.get("agent_id")
        if not agent_id:
            await ws.accept()
            await _send_error(ws, "mcp", ErrorCode.NO_AGENT, "agent_id required")
            await ws.close()
            return

        bundle = await _get_channel_bundle(agent_id)
        if bundle is None:
            await ws.accept()
            await _send_error(ws, "mcp", ErrorCode.NO_AGENT, "unknown agent")
            await ws.close()
            return

        client_id = str(uuid4())
        await bundle.mcp.connect(client_id, ws)
        await _send_accepted(ws, "mcp")

        # Send initial snapshot
        runtime = app.state.registry.get(agent_id)
        if runtime:
            await bundle.mcp.send_snapshot(runtime.running.compositor)

        try:
            # MCP channel is read-only from client perspective
            while True:
                await ws.receive_text()  # Keepalive, ignore content
        except WebSocketDisconnect:
            await bundle.mcp.disconnect(client_id)

    @app.websocket("/ws/approvals")
    async def ws_approvals(ws: WebSocket) -> None:
        """Approvals channel - tool approval requests and decisions."""
        agent_id = ws.query_params.get("agent_id")
        if not agent_id:
            await ws.accept()
            await _send_error(ws, "approvals", ErrorCode.NO_AGENT, "agent_id required")
            await ws.close()
            return

        bundle = await _get_channel_bundle(agent_id)
        if bundle is None:
            await ws.accept()
            await _send_error(ws, "approvals", ErrorCode.NO_AGENT, "unknown agent")
            await ws.close()
            return

        client_id = str(uuid4())
        await bundle.approvals.connect(client_id, ws)
        await _send_accepted(ws, "approvals")

        # Send initial snapshot
        runtime = app.state.registry.get(agent_id)
        if runtime:
            await bundle.approvals.send_snapshot(runtime.running.approval_hub)

        try:
            # Approvals channel is read-only from client perspective (approvals via HTTP)
            while True:
                await ws.receive_text()  # Keepalive, ignore content
        except WebSocketDisconnect:
            await bundle.approvals.disconnect(client_id)

    @app.websocket("/ws/policy")
    async def ws_policy(ws: WebSocket) -> None:
        """Policy channel - approval policy content and proposals."""
        agent_id = ws.query_params.get("agent_id")
        if not agent_id:
            await ws.accept()
            await _send_error(ws, "policy", ErrorCode.NO_AGENT, "agent_id required")
            await ws.close()
            return

        bundle = await _get_channel_bundle(agent_id)
        if bundle is None:
            await ws.accept()
            await _send_error(ws, "policy", ErrorCode.NO_AGENT, "unknown agent")
            await ws.close()
            return

        client_id = str(uuid4())
        await bundle.policy.connect(client_id, ws)
        await _send_accepted(ws, "policy")

        # Send initial snapshot
        runtime = app.state.registry.get(agent_id)
        if runtime:
            await bundle.policy.send_snapshot(runtime.running.approval_engine)

        try:
            # Policy channel is read-only from client perspective (updates via HTTP)
            while True:
                await ws.receive_text()  # Keepalive, ignore content
        except WebSocketDisconnect:
            await bundle.policy.disconnect(client_id)

    @app.websocket("/ws/session")
    async def ws_session(ws: WebSocket) -> None:
        """Session channel - agent execution state and transcript."""
        agent_id = ws.query_params.get("agent_id")
        if not agent_id:
            await ws.accept()
            await _send_error(ws, "session", ErrorCode.NO_AGENT, "agent_id required")
            await ws.close()
            return

        bundle = await _get_channel_bundle(agent_id)
        if bundle is None:
            await ws.accept()
            await _send_error(ws, "session", ErrorCode.NO_AGENT, "unknown agent")
            await ws.close()
            return

        if bundle.session is None:
            await ws.accept()
            await _send_error(ws, "session", ErrorCode.COMPONENT_UNAVAILABLE, "session not available")
            await ws.close()
            return

        client_id = str(uuid4())
        await bundle.session.connect(client_id, ws)
        await _send_accepted(ws, "session")

        # Send initial snapshot
        runtime = app.state.registry.get(agent_id)
        if runtime and runtime.runtime.session:
            await bundle.session.send_snapshot(runtime.runtime.session)

        try:
            # Session channel is read-only from client perspective (actions via HTTP)
            while True:
                await ws.receive_text()  # Keepalive, ignore content
        except WebSocketDisconnect:
            await bundle.session.disconnect(client_id)

    @app.websocket("/ws/ui")
    async def ws_ui(ws: WebSocket) -> None:
        """UI channel - UI state and custom messages."""
        agent_id = ws.query_params.get("agent_id")
        if not agent_id:
            await ws.accept()
            await _send_error(ws, "ui", ErrorCode.NO_AGENT, "agent_id required")
            await ws.close()
            return

        bundle = await _get_channel_bundle(agent_id)
        if bundle is None:
            await ws.accept()
            await _send_error(ws, "ui", ErrorCode.NO_AGENT, "unknown agent")
            await ws.close()
            return

        if bundle.ui is None:
            await ws.accept()
            await _send_error(ws, "ui", ErrorCode.COMPONENT_UNAVAILABLE, "ui not available")
            await ws.close()
            return

        client_id = str(uuid4())
        await bundle.ui.connect(client_id, ws)
        await _send_accepted(ws, "ui")

        # Send initial snapshot
        runtime = app.state.registry.get(agent_id)
        if runtime and runtime.runtime.session:
            ui_state = runtime.runtime.session.ui_state
            await bundle.ui.send_state_snapshot(ui_state, ui_state.seq)

        try:
            # UI channel is read-only from client perspective
            while True:
                await ws.receive_text()  # Keepalive, ignore content
        except WebSocketDisconnect:
            await bundle.ui.disconnect(client_id)
