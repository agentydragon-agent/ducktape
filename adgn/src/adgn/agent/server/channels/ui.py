"""UI channel - UI state and custom messages.

Component: AgentRuntime._ui_manager (optional)
Availability: Only when UI manager is attached
Messages: UI state snapshots, UI messages, end turn events
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.server.bus import MimeType
from adgn.agent.server.channels.base import ChannelConnectionManager
from adgn.agent.server.state import UiState


# ============================================================================
# Protocol Messages
# ============================================================================


class UiStateSnapshot(BaseModel):
    """Full UI state snapshot."""

    type: Literal["ui_state_snapshot"] = "ui_state_snapshot"
    v: Literal["ui_state_v1"] = "ui_state_v1"
    seq: int
    state: UiState
    model_config = ConfigDict(extra="forbid")


class UiStateUpdated(BaseModel):
    """UI state update event."""

    type: Literal["ui_state_updated"] = "ui_state_updated"
    v: Literal["ui_state_v1"] = "ui_state_v1"
    seq: int
    state: UiState
    model_config = ConfigDict(extra="forbid")


class UiMessagePayload(BaseModel):
    """UI message payload."""

    mime: MimeType = MimeType.MARKDOWN
    content: str
    model_config = ConfigDict(extra="forbid")


class UiMessageEvt(BaseModel):
    """UI message event."""

    type: Literal["ui_message"] = "ui_message"
    message: UiMessagePayload
    model_config = ConfigDict(extra="forbid")


class UiEndTurnEvt(BaseModel):
    """UI turn end event."""

    type: Literal["ui_end_turn"] = "ui_end_turn"
    model_config = ConfigDict(extra="forbid")


UiMessage = Annotated[
    UiStateSnapshot | UiStateUpdated | UiMessageEvt | UiEndTurnEvt,
    Field(discriminator="type"),
]


# ============================================================================
# Connection Manager
# ============================================================================


class UiChannelManager(ChannelConnectionManager):
    """Manages WebSocket connections for the UI channel.

    Broadcasts UI state and custom messages to connected clients.
    Only available when UI manager is attached (optional component).
    """

    def __init__(self):
        super().__init__("ui")

    async def send_state_snapshot(self, ui_state: UiState, seq: int) -> None:
        """Send current UI state snapshot to all clients."""
        snapshot = UiStateSnapshot(seq=seq, state=ui_state)
        await self.broadcast(snapshot)
