"""Base channel connection manager."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from pydantic import BaseModel

from adgn.agent.server.channels.protocol import ChannelEnvelope


class ChannelConnectionManager:
    """Base class for managing WebSocket connections to a single channel.

    Each channel has its own connection manager that handles:
    - Connection lifecycle (connect/disconnect)
    - Message broadcasting to all connected clients
    - Event ID sequencing
    - JSON serialization
    """

    def __init__(self, channel_name: str):
        self.channel_name = channel_name
        self._clients: dict[str, WebSocket] = {}
        self._event_id = 0

    def _next_event_id(self) -> int:
        self._event_id += 1
        return self._event_id

    async def connect(self, client_id: str, ws: WebSocket) -> None:
        """Add a new client connection."""
        await ws.accept()
        self._clients[client_id] = ws

    async def disconnect(self, client_id: str) -> None:
        """Remove a client connection."""
        self._clients.pop(client_id, None)

    async def send_to_client(self, client_id: str, payload: BaseModel) -> None:
        """Send a message to a specific client."""
        ws = self._clients.get(client_id)
        if ws is None:
            return

        envelope = ChannelEnvelope(
            channel=self.channel_name,
            event_id=self._next_event_id(),
            event_at=datetime.now(UTC),
            payload=payload,
        )

        try:
            await ws.send_json(envelope.model_dump(mode="json"))
        except Exception:
            # Client disconnected, remove them
            await self.disconnect(client_id)

    async def broadcast(self, payload: BaseModel) -> None:
        """Send a message to all connected clients."""
        if not self._clients:
            return

        envelope = ChannelEnvelope(
            channel=self.channel_name,
            event_id=self._next_event_id(),
            event_at=datetime.now(UTC),
            payload=payload,
        )

        data = envelope.model_dump(mode="json")
        dead_clients = []

        for client_id, ws in list(self._clients.items()):
            try:
                await ws.send_json(data)
            except Exception:
                dead_clients.append(client_id)

        # Clean up disconnected clients
        for client_id in dead_clients:
            await self.disconnect(client_id)

    async def flush(self) -> None:
        """Flush any pending messages (no-op for base implementation)."""
        pass

    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        return len(self._clients)
