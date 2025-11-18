"""Unified cross-agent management MCP server.

Provides resources and tools for managing multiple agents from a single connection.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

from adgn.agent.approvals import ApprovalRequest
from adgn.agent.persist import ApprovalOutcome, ApprovalRecord
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

if TYPE_CHECKING:
    from adgn.agent.mcp_bridge.server import InfrastructureRegistry
    from mcp import types as mcp_types

logger = logging.getLogger(__name__)


# Helper functions for data conversion


def _convert_pending_approvals(pending_map: dict[str, ApprovalRequest]) -> list[PendingApproval]:
    result: list[PendingApproval] = []
    for call_id, request in pending_map.items():
        args = {}
        if request.tool_call.args_json:
            try:
                args = json.loads(request.tool_call.args_json)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse args_json for call_id {call_id}")

        result.append(
            PendingApproval(
                call_id=call_id,
                tool=request.tool_call.name,
                args=args,
                timestamp=datetime.now(),  # TODO: Track creation time in ApprovalRequest
            )
        )
    return result


def _convert_approval_record_to_history(record: ApprovalRecord) -> ApprovalHistoryEntry:
    if record.outcome in (ApprovalOutcome.POLICY_ALLOW, ApprovalOutcome.USER_APPROVE):
        decision = DecisionType.APPROVED
        reason = None
    else:
        decision = DecisionType.REJECTED
        reason = record.details.get("reason") if record.details else None
        if not reason:
            reason = f"Denied by {record.outcome.value}"

    args = record.details.get("args", {}) if record.details else {}
    decided_by = record.details.get("decided_by", "human") if record.details else "human"

    return ApprovalHistoryEntry(
        call_id=record.call_id,
        tool=record.tool_key,
        args=args,
        decision=decision,
        reason=reason,
        timestamp=record.decided_at,
        decided_by=decided_by,
    )


# Enumerations
class DecisionType(StrEnum):
    """Approval decision types."""

    APPROVED = "approved"
    REJECTED = "rejected"


class AgentMode(StrEnum):
    """Agent mode enumeration."""

    LOCAL = "local"
    BRIDGE = "bridge"


class ApprovalStatus(StrEnum):
    """Approval tool response status."""

    APPROVED = "approved"
    REJECTED = "rejected"


class AbortStatus(StrEnum):
    """Abort tool response status."""

    ABORTED = "aborted"


# Tool input models
class ApproveToolCallArgs(BaseModel):
    """Arguments for approve_tool_call tool."""

    agent_id: str
    call_id: str


class RejectToolCallArgs(BaseModel):
    """Arguments for reject_tool_call tool."""

    agent_id: str
    call_id: str
    reason: str


class AbortAgentArgs(BaseModel):
    """Arguments for abort_agent tool."""

    agent_id: str


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

    agent_id: str
    capabilities: dict[str, bool]  # e.g., {"chat": True, "agent_loop": False}
    mode: AgentMode
    state_uri: str | None = None
    approvals_uri: str | None = None


class AgentListResponse(BaseModel):
    """Response for resource://agents/list."""

    agents: list[AgentInfo]


class AgentApprovalsPendingResponse(BaseModel):
    """Response for resource://agents/{id}/approvals/pending."""

    agent_id: str
    pending: list[PendingApproval]


class AgentApprovalsHistoryResponse(BaseModel):
    """Response for resource://agents/{id}/approvals/history."""

    agent_id: str
    timeline: list[ApprovalHistoryEntry]
    pending: list[PendingApproval]  # Pending approvals not yet decided
    count: int  # Total count (timeline + pending)


# Tool response models
class ApprovalToolResponse(BaseModel):
    """Response from approval tools (approve/reject)."""

    status: ApprovalStatus
    agent_id: str
    call_id: str


class AbortAgentResponse(BaseModel):
    """Response from abort_agent tool."""

    status: AbortStatus
    agent_id: str


def make_agents_server(registry: InfrastructureRegistry) -> NotifyingFastMCP:
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
        "resource://agents/list", name="agents.list", mime_type="application/json", description="List all agents with capabilities and state"
    )
    async def list_agents() -> AgentListResponse:
        agent_infos: list[AgentInfo] = []
        for agent_id in registry.known_agents():
            mode = registry.get_agent_mode(agent_id)

            # Assume bridge agents have no chat/agent_loop
            # TODO: Add capability tracking to registry if needed
            is_local = mode == AgentMode.LOCAL
            capabilities = {
                "chat": is_local,
                "agent_loop": is_local,
            }

            state_uri = f"resource://agents/{agent_id}/state" if is_local else None
            approvals_uri = f"resource://agents/{agent_id}/approvals/pending"

            agent_info = AgentInfo(
                agent_id=agent_id, capabilities=capabilities, mode=mode, state_uri=state_uri, approvals_uri=approvals_uri
            )
            agent_infos.append(agent_info)

        return AgentListResponse(agents=agent_infos)

    @server.resource(
        "resource://agents/{agent_id}/state",
        name="agent.state",
        mime_type="application/json",
        description="Sampling state for a local agent",
    )
    async def agent_state(agent_id: str):
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
    async def agent_approvals_pending(agent_id: str) -> AgentApprovalsPendingResponse:
        infra = await registry.get_infrastructure(agent_id)
        pending = _convert_pending_approvals(infra.approval_hub.pending)
        return AgentApprovalsPendingResponse(agent_id=agent_id, pending=pending)

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
        from mcp import types as mcp_types

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
                block = mcp_types.TextResourceContents(uri=approval_uri, mimeType="application/json", text=json.dumps(approval_data))
                content_blocks.append(block)

        return mcp_types.ReadResourceResult(contents=content_blocks)

    @server.resource(
        "resource://agents/{agent_id}/approvals/history",
        name="agent.approvals.history",
        mime_type="application/json",
        description="Historical approval timeline for an agent (activity log)",
    )
    async def agent_approvals_history(agent_id: str) -> AgentApprovalsHistoryResponse:
        """Includes both pending (not yet decided) and completed approvals."""
        infra = await registry.get_infrastructure(agent_id)

        approval_records = await infra.approval_engine.persistence.list_approvals(agent_id=agent_id, limit=100)
        completed_entries = [_convert_approval_record_to_history(record) for record in approval_records]

        pending_approvals = _convert_pending_approvals(infra.approval_hub.pending)

        # Count includes both completed and pending
        total_count = len(completed_entries) + len(pending_approvals)

        return AgentApprovalsHistoryResponse(
            agent_id=agent_id, timeline=completed_entries, pending=pending_approvals, count=total_count
        )

    # Tools

    @server.tool()
    async def approve_tool_call(agent_id: str, call_id: str) -> ApprovalToolResponse:
        from adgn.agent.handler import ContinueDecision

        infra = await registry.get_infrastructure(agent_id)
        infra.approval_hub.resolve(call_id, ContinueDecision())

        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/pending")
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/history")
        await server.broadcast_resource_updated("resource://approvals/pending")

        return ApprovalToolResponse(status=ApprovalStatus.APPROVED, agent_id=agent_id, call_id=call_id)

    @server.tool()
    async def reject_tool_call(agent_id: str, call_id: str, reason: str) -> ApprovalToolResponse:
        from adgn.agent.handler import AbortTurnDecision

        infra = await registry.get_infrastructure(agent_id)
        infra.approval_hub.resolve(call_id, AbortTurnDecision(reason=reason))

        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/pending")
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/history")
        await server.broadcast_resource_updated("resource://approvals/pending")

        return ApprovalToolResponse(status=ApprovalStatus.REJECTED, agent_id=agent_id, call_id=call_id)

    @server.tool()
    async def abort_agent(agent_id: str) -> AbortAgentResponse:
        """Raises ValueError if agent is not local or has no agent loop."""
        if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {agent_id} is not a local agent (cannot abort)")

        local_runtime = registry.get_local_runtime(agent_id)
        if local_runtime is None or local_runtime.agent is None:
            raise ValueError(f"Agent {agent_id} has no agent loop")

        await local_runtime.agent.abort()
        return AbortAgentResponse(status=AbortStatus.ABORTED, agent_id=agent_id)

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
                    import asyncio

                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(server.broadcast_resource_updated(uri))
                    except RuntimeError:
                        logger.warning(f"Could not broadcast {uri}: no running event loop")

                return notifier

            infra.approval_engine.set_notifier(make_policy_notifier(agent_id))

        except Exception as e:
            logger.warning(f"Failed to hook listeners for {agent_id}: {e}")

    return server
