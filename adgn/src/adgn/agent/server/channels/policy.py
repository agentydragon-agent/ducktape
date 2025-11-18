"""Policy channel - approval policy state and proposals.

Component: RunningInfrastructure.approval_engine
Availability: Always (policy engine in infrastructure)
Messages: policy content, version, proposals
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.models.policy_error import PolicyTestsSummary
from adgn.agent.models.proposal_status import ProposalStatus
from adgn.agent.server.channels.base import ChannelConnectionManager

if TYPE_CHECKING:
    from adgn.agent.approvals import ApprovalPolicyEngine


# ============================================================================
# Protocol Messages
# ============================================================================


class ProposalInfo(BaseModel):
    """Policy proposal information."""

    id: str
    status: ProposalStatus
    docstring: str | None = None
    tests: PolicyTestsSummary | None = None
    model_config = ConfigDict(extra="forbid")


class ApprovalPolicyInfo(BaseModel):
    """Current approval policy state."""

    content: str
    version: int
    proposals: list[ProposalInfo] = []
    model_config = ConfigDict(extra="forbid")


class PolicySnapshot(BaseModel):
    """Full policy state snapshot."""

    type: Literal["policy_snapshot"] = "policy_snapshot"
    policy: ApprovalPolicyInfo
    model_config = ConfigDict(extra="forbid")


class PolicyUpdated(BaseModel):
    """Policy updated event."""

    type: Literal["policy_updated"] = "policy_updated"
    version: int
    model_config = ConfigDict(extra="forbid")


class PolicyProposalEvt(BaseModel):
    """Policy proposal event."""

    type: Literal["policy_proposal"] = "policy_proposal"
    proposal: ProposalInfo
    model_config = ConfigDict(extra="forbid")


PolicyMessage = Annotated[
    PolicySnapshot | PolicyUpdated | PolicyProposalEvt,
    Field(discriminator="type"),
]


# ============================================================================
# Connection Manager
# ============================================================================


class PolicyChannelManager(ChannelConnectionManager):
    """Manages WebSocket connections for the policy channel.

    Broadcasts policy content, version, and proposals to connected clients.
    Always available (policy engine is in RunningInfrastructure).
    """

    def __init__(self):
        super().__init__("policy")

    async def send_snapshot(self, approval_engine: ApprovalPolicyEngine) -> None:
        """Send current policy snapshot to all clients."""
        content, version = approval_engine.get_policy()
        # TODO: Load proposals from persistence
        await self.broadcast(
            PolicySnapshot(policy=ApprovalPolicyInfo(content=content, version=version, proposals=[]))
        )


# ============================================================================
# WebSocket Endpoint
# ============================================================================


def register_endpoint(app):
    """Register policy channel WebSocket endpoint."""
    from fastapi import FastAPI, WebSocket

    from adgn.agent.server.channels.common import handle_channel_ws

    @app.websocket("/ws/policy")
    async def ws_policy(ws: WebSocket) -> None:
        """Policy channel - approval policy content and proposals."""
        await handle_channel_ws(
            ws,
            "policy",
            ws.query_params.get("agent_id"),
            lambda b: b.policy,
            lambda b, aid: b.policy.send_snapshot(app.state.registry.get(aid).running.approval_engine)
            if app.state.registry.get(aid)
            else None,
            app,
        )
