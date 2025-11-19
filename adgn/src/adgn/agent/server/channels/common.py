"""Common protocol messages and utilities used across all channels."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from fastapi import FastAPI

    from adgn.agent.server.channels.bundle import ChannelBundle

logger = logging.getLogger(__name__)


class ChannelEnvelope(BaseModel):
    """Generic envelope for all channel messages."""

    channel: str
    event_id: int
    event_at: datetime
    payload: BaseModel
    model_config = ConfigDict(extra="forbid")


class Accepted(BaseModel):
    """Connection accepted acknowledgment."""

    type: Literal["accepted"] = "accepted"
    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    INVALID_JSON = "INVALID_JSON"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_COMMAND = "INVALID_COMMAND"
    NO_AGENT = "NO_AGENT"
    AGENT_ERROR = "AGENT_ERROR"
    COMPONENT_UNAVAILABLE = "COMPONENT_UNAVAILABLE"


class ErrorEvt(BaseModel):
    """Error event."""

    type: Literal["error"] = "error"
    code: ErrorCode
    message: str | None = None
    details: dict | None = None
    model_config = ConfigDict(extra="forbid")


class HeartbeatEvt(BaseModel):
    """Heartbeat keepalive."""

    type: Literal["heartbeat"] = "heartbeat"
    interval_ms: int
    model_config = ConfigDict(extra="forbid")


# ============================================================================
# Common WebSocket Helpers
# ============================================================================


async def send_envelope(ws: WebSocket, channel: str, payload: Accepted | ErrorEvt) -> None:
    """Send envelope to client, ignoring errors."""

    envelope = ChannelEnvelope(channel=channel, event_id=0, event_at=datetime.now(UTC), payload=payload)
    with contextlib.suppress(Exception):
        await ws.send_json(envelope.model_dump(mode="json"))


async def get_channel_bundle(app: FastAPI, agent_id: str) -> ChannelBundle | None:
    """Get or create channel bundle for agent."""
    # Import here to avoid circular dependency
    from adgn.agent.server.channels.bundle import ChannelBundle

    await app.state.ready.wait()
    try:
        runtime = await app.state.registry.ensure_live(agent_id, with_ui=True)
    except KeyError:
        return None
    except Exception as e:
        logger.exception("ensure_live failed", exc_info=e)
        return None

    if runtime._channel_bundle is None:
        runtime._channel_bundle = ChannelBundle.for_agent_runtime(runtime)
    bundle: ChannelBundle = runtime._channel_bundle  # type: ignore[assignment]
    return bundle


async def handle_channel_ws(
    ws: WebSocket, channel: str, agent_id: str | None, get_manager, send_initial_snapshot, app: FastAPI
):
    """Common WebSocket handler pattern for all channels."""
    await ws.accept()
    try:
        if not agent_id:
            await send_envelope(ws, channel, ErrorEvt(code=ErrorCode.NO_AGENT, message="agent_id required"))
            return

        bundle = await get_channel_bundle(app, agent_id)
        if bundle is None:
            await send_envelope(ws, channel, ErrorEvt(code=ErrorCode.NO_AGENT, message="unknown agent"))
            return

        manager = get_manager(bundle)
        if manager is None:
            await send_envelope(
                ws, channel, ErrorEvt(code=ErrorCode.COMPONENT_UNAVAILABLE, message=f"{channel} not available")
            )
            return

        client_id = str(uuid4())
        await manager.connect(client_id, ws)
        await send_envelope(ws, channel, Accepted())

        await send_initial_snapshot(bundle, agent_id)

        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            await manager.disconnect(client_id)
    finally:
        await ws.close()
