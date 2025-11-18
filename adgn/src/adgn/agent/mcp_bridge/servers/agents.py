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
    """Convert ApprovalHub pending map to list of PendingApproval models.

    Args:
        pending_map: Dict of call_id -> ApprovalRequest from ApprovalHub

    Returns:
        List of PendingApproval Pydantic models
    """
    result: list[PendingApproval] = []
    for call_id, request in pending_map.items():
        # Parse args_json if present
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
    """Convert persistence ApprovalRecord to ApprovalHistoryEntry.

    Args:
        record: ApprovalRecord from persistence

    Returns:
        ApprovalHistoryEntry for MCP response
    """
    # Map outcome to decision type
    if record.outcome in (ApprovalOutcome.POLICY_ALLOW, ApprovalOutcome.USER_APPROVE):
        decision = DecisionType.APPROVED
        reason = None
    else:
        decision = DecisionType.REJECTED
        # Extract reason from details if present
        reason = record.details.get("reason") if record.details else None
        if not reason:
            reason = f"Denied by {record.outcome.value}"

    # Extract args from details
    args = record.details.get("args", {}) if record.details else {}

    # Extract decided_by from details
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

    Provides resources and tools for viewing and managing all agents through
    a single MCP connection. Can be delegated to other agents for self-orchestration.

    Args:
        registry: InfrastructureRegistry with all registered agents

    Returns:
        NotifyingFastMCP server instance
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
        """List all known agents.

        Returns AgentListResponse with all agent metadata, capabilities, and URIs.
        All data constructed using Pydantic models.
        """
        agent_infos: list[AgentInfo] = []
        for agent_id in registry.known_agents():
            # Get mode from registry (no hasattr)
            mode = registry.get_agent_mode(agent_id)

            # Build capabilities dict
            # For now, assume bridge agents have no chat/agent_loop
            # TODO: Add capability tracking to registry if needed
            is_local = mode == AgentMode.LOCAL
            capabilities = {
                "chat": is_local,  # Local agents have chat
                "agent_loop": is_local,  # Local agents have agent loop
            }

            # Determine optional URIs based on mode
            state_uri = f"resource://agents/{agent_id}/state" if is_local else None
            approvals_uri = f"resource://agents/{agent_id}/approvals/pending"

            # Construct Pydantic model
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
        """Get sampling state for local agent.

        Raises:
            ValueError: If agent is not local or has no runtime
        """
        # Check mode via registry (no hasattr)
        if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {agent_id} is not a local agent")

        # Get local runtime to access sampling state
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
        """Get pending approvals for agent.

        Returns AgentApprovalsPendingResponse with pending approvals.
        All data constructed using Pydantic models.
        """
        infra = await registry.get_infrastructure(agent_id)

        # Convert ApprovalHub pending map to list of PendingApproval models
        pending = _convert_pending_approvals(infra.approval_hub.pending)

        return AgentApprovalsPendingResponse(agent_id=agent_id, pending=pending)

    @server.resource(
        "resource://approvals/pending",
        name="approvals.pending.global",
        mime_type="application/json",
        description="Global mailbox: all pending approvals across all agents (returns multiple content blocks)",
    )
    async def approvals_pending_global():
        """Get all pending approvals as MCP content blocks (global mailbox).

        Returns mcp_types.ReadResourceResult with multiple TextResourceContents blocks.
        Each approval is a separate content block with:
        - uri: unique resource URI for this approval
        - mimeType: application/json
        - text: inline JSON content with approval details

        All data constructed using Pydantic models. Crashes if any agent fails
        (no exception swallowing).
        """
        from mcp import types as mcp_types

        content_blocks: list[mcp_types.TextResourceContents] = []

        for agent_id in registry.known_agents():
            infra = await registry.get_infrastructure(agent_id)

            # Convert ApprovalHub pending map to list of PendingApproval models
            pending_approvals = _convert_pending_approvals(infra.approval_hub.pending)

            for approval in pending_approvals:
                # Construct MCP TextResourceContents for each approval
                approval_uri = f"resource://agents/{agent_id}/approvals/{approval.call_id}"
                approval_data = {
                    "agent_id": agent_id,
                    "call_id": approval.call_id,
                    "tool": approval.tool,
                    "args": approval.args,
                    "timestamp": approval.timestamp.isoformat(),
                }
                # Use MCP types directly - each block is a TextResourceContents
                block = mcp_types.TextResourceContents(uri=approval_uri, mimeType="application/json", text=json.dumps(approval_data))
                content_blocks.append(block)

        # Return ReadResourceResult with multiple content blocks
        return mcp_types.ReadResourceResult(contents=content_blocks)

    @server.resource(
        "resource://agents/{agent_id}/approvals/history",
        name="agent.approvals.history",
        mime_type="application/json",
        description="Historical approval timeline for an agent (activity log)",
    )
    async def agent_approvals_history(agent_id: str) -> AgentApprovalsHistoryResponse:
        """Get historical approval timeline for an agent.

        Serves as activity log for external agents - shows what tool calls
        were approved/rejected, when, and by whom (human or which agent).

        Includes both pending approvals (not yet decided) and completed approvals.
        All data routed through Pydantic models for type safety.
        """
        infra = await registry.get_infrastructure(agent_id)

        # Get completed approvals from persistence
        approval_records = await infra.approval_engine.persistence.list_approvals(agent_id=agent_id, limit=100)
        completed_entries = [_convert_approval_record_to_history(record) for record in approval_records]

        # Get pending approvals from approval hub
        pending_approvals = _convert_pending_approvals(infra.approval_hub.pending)

        # Total count includes both completed and pending
        total_count = len(completed_entries) + len(pending_approvals)

        # Return Pydantic response model directly (FastMCP handles serialization)
        return AgentApprovalsHistoryResponse(
            agent_id=agent_id, timeline=completed_entries, pending=pending_approvals, count=total_count
        )

    # Tools

    @server.tool()
    async def approve_tool_call(agent_id: str, call_id: str) -> ApprovalToolResponse:
        """Approve a pending tool call.

        Args:
            agent_id: Agent identifier
            call_id: Tool call identifier

        Returns:
            ApprovalToolResponse with approval confirmation

        Routes to: lookup_infrastructure(agent_id).approval_hub.resolve()
        """
        from adgn.agent.handler import ContinueDecision

        infra = await registry.get_infrastructure(agent_id)
        infra.approval_hub.resolve(call_id, ContinueDecision())

        # Broadcast resource updates for pending approvals and history
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/pending")
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/history")
        await server.broadcast_resource_updated("resource://approvals/pending")

        return ApprovalToolResponse(status=ApprovalStatus.APPROVED, agent_id=agent_id, call_id=call_id)

    @server.tool()
    async def reject_tool_call(agent_id: str, call_id: str, reason: str) -> ApprovalToolResponse:
        """Reject a pending tool call.

        Args:
            agent_id: Agent identifier
            call_id: Tool call identifier
            reason: Rejection reason

        Returns:
            ApprovalToolResponse with rejection confirmation

        Routes to: lookup_infrastructure(agent_id).approval_hub.resolve()
        """
        from adgn.agent.handler import AbortTurnDecision

        infra = await registry.get_infrastructure(agent_id)
        infra.approval_hub.resolve(call_id, AbortTurnDecision(reason=reason))

        # Broadcast resource updates for pending approvals and history
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/pending")
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/history")
        await server.broadcast_resource_updated("resource://approvals/pending")

        return ApprovalToolResponse(status=ApprovalStatus.REJECTED, agent_id=agent_id, call_id=call_id)

    @server.tool()
    async def abort_agent(agent_id: str) -> AbortAgentResponse:
        """Abort a running agent.

        Args:
            agent_id: Agent identifier

        Returns:
            AbortAgentResponse with abort confirmation

        Routes to: local_runtime.agent.abort()

        Raises:
            ValueError: If agent is not local or has no agent loop
        """
        # Check mode via registry (no hasattr)
        if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {agent_id} is not a local agent (cannot abort)")

        # Get local runtime
        local_runtime = registry.get_local_runtime(agent_id)
        if local_runtime is None or local_runtime.agent is None:
            raise ValueError(f"Agent {agent_id} has no agent loop")

        await local_runtime.agent.abort()
        return AbortAgentResponse(status=AbortStatus.ABORTED, agent_id=agent_id)

    # Wire up notifications
    # Note: Notifications are triggered when:
    # 1. Approval decisions are made (approve/reject tools)
    # 2. Approval policy changes (already wired through ApprovalPolicyEngine)
    # 3. Agent state changes (for local agents)

    # For approval changes, we trigger notifications directly in the approve/reject tools
    # since ApprovalHub doesn't have a built-in notification system

    # For policy changes, ApprovalPolicyEngine already has a notifier callback
    # We can enhance it to also notify about approval history changes

    # Hook up policy engine notifiers for all agents
    for agent_id in registry.known_agents():
        try:
            infra = await registry.get_infrastructure(agent_id)

            # Create a closure that captures agent_id for this specific agent
            def make_policy_notifier(aid: str):
                def notifier(uri: str):
                    # Schedule broadcast in event loop (notifier is sync)
                    import asyncio

                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(server.broadcast_resource_updated(uri))
                    except RuntimeError:
                        logger.warning(f"Could not broadcast {uri}: no running event loop")

                return notifier

            # Set notifier for policy engine
            infra.approval_engine.set_notifier(make_policy_notifier(agent_id))

        except Exception as e:
            logger.warning(f"Failed to hook listeners for {agent_id}: {e}")

    return server
