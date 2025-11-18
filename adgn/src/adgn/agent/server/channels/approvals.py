"""Approvals channel - tool approval requests and decisions.

Component: RunningInfrastructure.approval_hub
Availability: Always (approval hub in infrastructure)
Messages: pending approvals, approval decisions
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.server.channels.base import ChannelConnectionManager

if TYPE_CHECKING:
    from adgn.agent.approvals import ApprovalHub


# ============================================================================
# Protocol Messages
# ============================================================================


class ApprovalBrief(BaseModel):
    """Brief approval request info."""

    call_id: str
    tool_key: str
    args: dict = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")


class ApprovalsSnapshot(BaseModel):
    """Full approvals state snapshot."""

    type: Literal["approvals_snapshot"] = "approvals_snapshot"
    pending: list[ApprovalBrief] = []
    model_config = ConfigDict(extra="forbid")


class ApprovalPendingEvt(BaseModel):
    """New approval request event."""

    type: Literal["approval_pending"] = "approval_pending"
    call_id: str
    tool_key: str
    args_json: str | None = None
    model_config = ConfigDict(extra="forbid")


class ApprovalDecisionEvt(BaseModel):
    """Approval decision event."""

    type: Literal["approval_decision"] = "approval_decision"
    call_id: str
    decision: Literal["approve", "deny_continue", "deny_abort"]
    model_config = ConfigDict(extra="forbid")


ApprovalsMessage = Annotated[ApprovalsSnapshot | ApprovalPendingEvt | ApprovalDecisionEvt, Field(discriminator="type")]


# ============================================================================
# Connection Manager
# ============================================================================


class ApprovalsChannelManager(ChannelConnectionManager):
    """Manages WebSocket connections for the approvals channel.

    Broadcasts approval requests and decisions to connected clients.
    Always available (approval hub is in RunningInfrastructure).
    """

    def __init__(self):
        super().__init__("approvals")

    async def send_snapshot(self, approval_hub: ApprovalHub) -> None:
        """Send current approvals snapshot to all clients."""
        pending = [
            ApprovalBrief(call_id=req.tool_call.call_id, tool_key=req.tool_key, args={})
            for req in approval_hub._requests.values()
        ]
        snapshot = ApprovalsSnapshot(pending=pending)
        await self.broadcast(snapshot)


# ============================================================================
# WebSocket Endpoint
# ============================================================================


def register_endpoint(app):
    """Register approvals channel WebSocket endpoint."""
    from fastapi import WebSocket

    from adgn.agent.server.channels.common import handle_channel_ws

    @app.websocket("/ws/approvals")
    async def ws_approvals(ws: WebSocket) -> None:
        """Approvals channel - tool approval requests and decisions."""
        await handle_channel_ws(
            ws,
            "approvals",
            ws.query_params.get("agent_id"),
            lambda b: b.approvals,
            lambda b, aid: b.approvals.send_snapshot(app.state.registry.get(aid).running.approval_hub)
            if app.state.registry.get(aid)
            else None,
            app,
        )
