"""Unified cross-agent management MCP server.

Provides resources and tools for managing multiple agents from a single connection.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import StrEnum
import json
import logging
from typing import TYPE_CHECKING

from mcp import types as mcp_types
from pydantic import BaseModel

from adgn.agent.approvals import ApprovalRequest
from adgn.agent.handler import AbortTurnDecision, ContinueDecision
from adgn.agent.mcp_bridge.types import AgentID, AgentMode
from adgn.agent.persist import ApprovalOutcome, ToolCallRecord
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

if TYPE_CHECKING:
    from adgn.agent.mcp_bridge.server import InfrastructureRegistry

logger = logging.getLogger(__name__)


# Helper functions for data conversion


def _convert_pending_approvals(pending_map: dict[str, ApprovalRequest]) -> list[PendingApproval]:
    result: list[PendingApproval] = []
    for call_id, request in pending_map.items():
        args = json.loads(request.tool_call.args_json) if request.tool_call.args_json else {}

        result.append(
            PendingApproval(
                call_id=call_id,
                tool=request.tool_call.name,
                args=args,
                timestamp=datetime.now(),  # TODO: Track creation time in ApprovalRequest
            )
        )
    return result


def _convert_tool_call_record_to_history(record: ToolCallRecord) -> ApprovalHistoryEntry | None:
    """Convert ToolCallRecord to ApprovalHistoryEntry.

    Returns None for PENDING tool calls (decision=None), since they haven't been decided yet
    and belong in the pending list instead.
    """
    # Skip pending tool calls - they go in the pending list, not history
    if record.decision is None:
        return None

    # Determine decision type from outcome
    if record.decision.outcome in (ApprovalOutcome.POLICY_ALLOW, ApprovalOutcome.USER_APPROVE):
        decision = DecisionType.APPROVED
    else:
        decision = DecisionType.REJECTED

    # Extract reason
    reason = record.decision.reason
    if not reason and decision == DecisionType.REJECTED:
        reason = f"Denied by {record.decision.outcome.value}"

    # Parse args from JSON
    args = json.loads(record.tool_call.args_json) if record.tool_call.args_json else {}

    # Determine who made the decision
    if record.decision.outcome in (
        ApprovalOutcome.POLICY_ALLOW,
        ApprovalOutcome.POLICY_DENY_CONTINUE,
        ApprovalOutcome.POLICY_DENY_ABORT,
    ):
        decided_by = "policy"
    else:
        decided_by = "human"

    return ApprovalHistoryEntry(
        call_id=record.call_id,
        tool=record.tool_call.name,
        args=args,
        decision=decision,
        reason=reason,
        timestamp=record.decision.decided_at,
        decided_by=decided_by,
    )


# Enumerations
class DecisionType(StrEnum):
    """Approval decision types."""

    APPROVED = "approved"
    REJECTED = "rejected"


# Tool input models
class ApproveToolCallArgs(BaseModel):
    """Arguments for approve_tool_call tool."""

    agent_id: AgentID
    call_id: str


class RejectToolCallArgs(BaseModel):
    """Arguments for reject_tool_call tool."""

    agent_id: AgentID
    call_id: str
    reason: str


class AbortAgentArgs(BaseModel):
    """Arguments for abort_agent tool."""

    agent_id: AgentID


# Pending approval models
class PendingApproval(BaseModel):
    """A tool call awaiting approval."""

    call_id: str
    tool: str
    args: dict
    timestamp: datetime


# Historical approval timeline models
class ApprovalHistoryEntry(BaseModel):
    """Single approval decision in the timeline."""

    call_id: str
    tool: str
    args: dict
    decision: DecisionType
    reason: str | None = None  # Only for rejections
    timestamp: datetime
    decided_by: str  # "human" or agent ID


# Resource response models
class AgentInfo(BaseModel):
    """Information about a single agent."""

    agent_id: AgentID
    capabilities: dict[str, bool]  # e.g., {"chat": True, "agent_loop": False}
    mode: AgentMode
    state_uri: str | None = None
    approvals_uri: str | None = None
    policy_proposals_uri: str | None = None


class AgentList(BaseModel):
    """Content for resource://agents/list."""

    agents: list[AgentInfo]


class AgentApprovalsPending(BaseModel):
    """Content for resource://agents/{id}/approvals/pending."""

    agent_id: AgentID
    pending: list[PendingApproval]


class AgentApprovalsHistory(BaseModel):
    """Content for resource://agents/{id}/approvals/history."""

    agent_id: AgentID
    timeline: list[ApprovalHistoryEntry]
    pending: list[PendingApproval]  # Pending approvals not yet decided
    count: int  # Total count (timeline + pending)


class PolicyProposalInfo(BaseModel):
    """Policy proposal metadata with URI to full content."""

    id: str
    status: str
    created_at: datetime
    decided_at: datetime | None = None
    proposal_uri: str  # URI to access full proposal content in policy server


class AgentPolicyProposals(BaseModel):
    """Content for resource://agents/{id}/policy/proposals."""

    agent_id: AgentID
    proposals: list[PolicyProposalInfo]
    active_policy_uri: str  # URI to active policy


# Tool response models - empty responses, caller tracks what they called


async def make_agents_server(registry: InfrastructureRegistry) -> NotifyingFastMCP:
    """Unified cross-agent management server.

    Can be delegated to other agents for self-orchestration.
    """
    server = NotifyingFastMCP(
        name="agents",
        instructions="""Multi-agent management server.

        Provides cross-agent visibility and control:
        - List all agents with their capabilities
        - View sampling state for local agents
        - Approve/reject tool calls
        - Abort running agents

        Future: spawn agents, update policies, delegate work.""",
    )

    # Resources

    @server.resource(
        "resource://agents/list",
        name="agents.list",
        mime_type="application/json",
        description="List all agents with capabilities and state",
    )
    async def list_agents() -> AgentList:
        agent_infos: list[AgentInfo] = []
        for agent_id in registry.known_agents():
            mode = registry.get_agent_mode(agent_id)

            # Assume bridge agents have no chat/agent_loop
            # TODO: Add capability tracking to registry if needed
            is_local = mode == AgentMode.LOCAL
            capabilities = {"chat": is_local, "agent_loop": is_local}

            state_uri = f"resource://agents/{agent_id}/state" if is_local else None
            approvals_uri = f"resource://agents/{agent_id}/approvals/pending"
            policy_proposals_uri = f"resource://agents/{agent_id}/policy/proposals"

            agent_info = AgentInfo(
                agent_id=agent_id,
                capabilities=capabilities,
                mode=mode,
                state_uri=state_uri,
                approvals_uri=approvals_uri,
                policy_proposals_uri=policy_proposals_uri,
            )
            agent_infos.append(agent_info)

        return AgentList(agents=agent_infos)

    @server.resource(
        "resource://agents/{agent_id}/state",
        name="agent.state",
        mime_type="application/json",
        description="Sampling state for a local agent",
    )
    async def agent_state(agent_id: AgentID):
        """Raises ValueError if agent is not local or has no runtime."""
        if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {agent_id} is not a local agent")

        local_runtime = registry.get_local_runtime(agent_id)
        if local_runtime is None:
            raise ValueError(f"Agent {agent_id} has no local runtime")

        # TODO: Implement sampling snapshot retrieval
        # return await local_runtime.session.get_sampling_snapshot()
        raise NotImplementedError("Sampling snapshot not yet implemented")

    @server.resource(
        "resource://agents/{agent_id}/approvals/pending",
        name="agent.approvals.pending",
        mime_type="application/json",
        description="Pending approvals for a specific agent",
    )
    async def agent_approvals_pending(agent_id: AgentID) -> AgentApprovalsPending:
        infra = await registry.get_infrastructure(agent_id)
        pending = _convert_pending_approvals(infra.approval_hub.pending)
        return AgentApprovalsPending(agent_id=agent_id, pending=pending)

    @server.resource(
        "resource://approvals/pending",
        name="approvals.pending.global",
        mime_type="application/json",
        description="Global mailbox: all pending approvals across all agents (returns multiple content blocks)",
    )
    async def approvals_pending_global():
        """Each approval is a separate MCP TextResourceContents block.

        Crashes if any agent fails (no exception swallowing).
        """
        content_blocks: list[mcp_types.TextResourceContents] = []

        for agent_id in registry.known_agents():
            infra = await registry.get_infrastructure(agent_id)
            pending_approvals = _convert_pending_approvals(infra.approval_hub.pending)

            for approval in pending_approvals:
                approval_uri = f"resource://agents/{agent_id}/approvals/{approval.call_id}"
                approval_data = {
                    "agent_id": agent_id,
                    "call_id": approval.call_id,
                    "tool": approval.tool,
                    "args": approval.args,
                    "timestamp": approval.timestamp.isoformat(),
                }
                block = mcp_types.TextResourceContents(
                    uri=approval_uri, mimeType="application/json", text=json.dumps(approval_data)
                )
                content_blocks.append(block)

        return mcp_types.ReadResourceResult(contents=content_blocks)

    @server.resource(
        "resource://agents/{agent_id}/approvals/history",
        name="agent.approvals.history",
        mime_type="application/json",
        description="Historical approval timeline for an agent (activity log)",
    )
    async def agent_approvals_history(agent_id: AgentID) -> AgentApprovalsHistory:
        """Includes both pending (not yet decided) and completed approvals."""
        infra = await registry.get_infrastructure(agent_id)

        # Get all tool call records (limit to recent 100)
        # Note: list_tool_calls doesn't support agent_id filtering yet, so we get all and filter
        all_records = await infra.approval_engine.persistence.list_tool_calls()
        agent_records = [r for r in all_records if r.agent_id == agent_id][-100:]

        # Convert to history entries (filters out PENDING records)
        completed_entries = []
        for record in agent_records:
            entry = _convert_tool_call_record_to_history(record)
            if entry is not None:
                completed_entries.append(entry)

        pending_approvals = _convert_pending_approvals(infra.approval_hub.pending)

        # Count includes both completed and pending
        total_count = len(completed_entries) + len(pending_approvals)

        return AgentApprovalsHistory(
            agent_id=agent_id, timeline=completed_entries, pending=pending_approvals, count=total_count
        )

    @server.resource(
        "resource://agents/{agent_id}/policy/proposals",
        name="agent.policy.proposals",
        mime_type="application/json",
        description="Policy proposals for an agent (links to full proposals in policy server)",
    )
    async def agent_policy_proposals(agent_id: AgentID) -> AgentPolicyProposals:
        """Lists policy proposals with URIs to access full content in policy server."""
        infra = await registry.get_infrastructure(agent_id)
        proposals = await infra.approval_engine.persistence.list_policy_proposals(agent_id)

        proposal_infos = [
            PolicyProposalInfo(
                id=p.id,
                status=p.status,
                created_at=p.created_at,
                decided_at=p.decided_at,
                proposal_uri=f"resource://approval-policy/proposals/{p.id}",
            )
            for p in proposals
        ]

        return AgentPolicyProposals(
            agent_id=agent_id, proposals=proposal_infos, active_policy_uri="resource://approval-policy/policy.py"
        )

    # Tools

    @server.tool()
    async def approve_tool_call(agent_id: str, call_id: str) -> None:
        infra = await registry.get_infrastructure(AgentID(agent_id))
        infra.approval_hub.resolve(call_id, ContinueDecision())

        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/pending")
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/history")
        await server.broadcast_resource_updated("resource://approvals/pending")

    @server.tool()
    async def reject_tool_call(agent_id: str, call_id: str, reason: str) -> None:
        infra = await registry.get_infrastructure(AgentID(agent_id))
        infra.approval_hub.resolve(call_id, AbortTurnDecision(reason=reason))

        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/pending")
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/history")
        await server.broadcast_resource_updated("resource://approvals/pending")

    @server.tool()
    async def abort_agent(agent_id: AgentID) -> None:
        """Raises ValueError if agent is not local or has no agent loop."""
        if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {agent_id} is not a local agent (cannot abort)")

        local_runtime = registry.get_local_runtime(agent_id)
        if local_runtime is None or local_runtime.agent is None:
            raise ValueError(f"Agent {agent_id} has no agent loop")

        await local_runtime.agent.abort()  # type: ignore[attr-defined]  # TODO: Implement abort() on MiniCodex

    # Wire up notifications
    # For approval changes: notifications are broadcast directly in approve/reject tools
    # (ApprovalHub doesn't have built-in notification system)
    # For policy changes: wire policy engine notifier to broadcast MCP resource updates

    for agent_id in registry.known_agents():
        try:
            infra = await registry.get_infrastructure(agent_id)

            # Closure captures agent_id for this specific agent
            def make_policy_notifier(aid: str):
                def notifier(uri: str):
                    # Notifier is sync, schedule broadcast in event loop
                    try:
                        loop = asyncio.get_running_loop()
                        _task = loop.create_task(server.broadcast_resource_updated(uri))
                        # Don't await task - fire and forget notification
                        _task.add_done_callback(
                            lambda t: logger.debug(f"Broadcast complete for {uri}")
                            if not t.exception()
                            else logger.warning(f"Broadcast failed for {uri}: {t.exception()}")
                        )
                    except RuntimeError:
                        logger.warning(f"Could not broadcast {uri}: no running event loop")

                return notifier

            infra.approval_engine.set_notifier(make_policy_notifier(agent_id))

        except Exception as e:
            logger.warning(f"Failed to hook listeners for {agent_id}: {e}")

    return server
