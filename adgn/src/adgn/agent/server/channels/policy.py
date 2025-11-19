"""Policy channel - approval policy state and proposals.

Component: RunningInfrastructure.approval_engine
Availability: Always (policy engine in infrastructure)
Messages: policy content, id, proposals
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import WebSocket
from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.models.policy_error import PolicyTestsSummary
from adgn.agent.models.proposal_status import ProposalStatus
from adgn.agent.server.channels.base import ChannelConnectionManager
from adgn.agent.server.channels.common import handle_channel_ws

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
    id: int
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
    id: int
    model_config = ConfigDict(extra="forbid")


class PolicyProposalEvt(BaseModel):
    """Policy proposal event."""

    type: Literal["policy_proposal"] = "policy_proposal"
    proposal: ProposalInfo
    model_config = ConfigDict(extra="forbid")


PolicyMessage = Annotated[PolicySnapshot | PolicyUpdated | PolicyProposalEvt, Field(discriminator="type")]


# ============================================================================
# Connection Manager
# ============================================================================


class PolicyChannelManager(ChannelConnectionManager):
    """Manages WebSocket connections for the policy channel.

    Broadcasts policy content, id, and proposals to connected clients.
    Always available (policy engine is in RunningInfrastructure).
    """

    def __init__(self):
        super().__init__("policy")

    async def send_snapshot(self, approval_engine: ApprovalPolicyEngine) -> None:
        """Send current policy snapshot to all clients."""
        content, policy_id = approval_engine.get_policy()

        # Load proposals from persistence
        db_proposals = await approval_engine.persistence.list_policy_proposals(approval_engine.agent_id)
        proposals = [
            ProposalInfo(
                id=p.id,
                status=ProposalStatus(p.status),
                docstring=None,  # TODO: Extract from content if needed
                tests=None,  # TODO: Parse test results if available
            )
            for p in db_proposals
        ]

        await self.broadcast(
            PolicySnapshot(policy=ApprovalPolicyInfo(content=content, id=policy_id, proposals=proposals))
        )


# ============================================================================
# WebSocket Endpoint
# ============================================================================


def register_endpoint(app):
    """Register policy channel WebSocket endpoint."""

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
