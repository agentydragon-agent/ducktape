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

from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

if TYPE_CHECKING:
    from adgn.agent.mcp_bridge.server import InfrastructureRegistry
    from mcp import types as mcp_types

logger = logging.getLogger(__name__)


# Enumerations
class DecisionType(StrEnum):
    """Approval decision types."""

    APPROVED = "approved"
    REJECTED = "rejected"


class AgentMode(StrEnum):
    """Agent mode enumeration."""

    LOCAL = "local"
    BRIDGE = "bridge"


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
    count: int


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

        # TODO: Implement get_pending() method
        # pending: list[PendingApproval] = await infra.approval_engine.get_pending()
        pending: list[PendingApproval] = []

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

            # TODO: Implement get_pending() method
            # pending_approvals: list[PendingApproval] = await infra.approval_engine.get_pending()
            pending_approvals: list[PendingApproval] = []

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
        All data routed through Pydantic models for type safety.
        """
        infra = await registry.get_infrastructure(agent_id)

        # TODO: Implement get_history() method
        # history_entries: list[ApprovalHistoryEntry] = await infra.approval_engine.get_history()
        history_entries: list[ApprovalHistoryEntry] = []

        # Return Pydantic response model directly (FastMCP handles serialization)
        return AgentApprovalsHistoryResponse(agent_id=agent_id, timeline=history_entries, count=len(history_entries))

    # Tools

    @server.tool()
    async def approve_tool_call(agent_id: str, call_id: str) -> dict:
        """Approve a pending tool call.

        Args:
            agent_id: Agent identifier
            call_id: Tool call identifier

        Returns:
            Status dict with approval confirmation

        Routes to: lookup_infrastructure(agent_id).approval_hub.resolve()
        """
        infra = await registry.get_infrastructure(agent_id)

        # TODO: Implement approval via approval_hub
        # from adgn.agent.handler import ContinueDecision
        # infra.approval_hub.resolve(call_id, ContinueDecision())

        return {"status": "approved", "agent_id": agent_id, "call_id": call_id}

    @server.tool()
    async def reject_tool_call(agent_id: str, call_id: str, reason: str) -> dict:
        """Reject a pending tool call.

        Args:
            agent_id: Agent identifier
            call_id: Tool call identifier
            reason: Rejection reason

        Returns:
            Status dict with rejection confirmation

        Routes to: lookup_infrastructure(agent_id).approval_hub.resolve()
        """
        infra = await registry.get_infrastructure(agent_id)

        # TODO: Implement rejection via approval_hub
        # from adgn.agent.handler import AbortTurnDecision
        # infra.approval_hub.resolve(call_id, AbortTurnDecision(reason=reason))

        return {"status": "rejected", "agent_id": agent_id, "call_id": call_id}

    @server.tool()
    async def abort_agent(agent_id: str) -> dict:
        """Abort a running agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Status dict with abort confirmation

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
        return {"status": "aborted", "agent_id": agent_id}

    # Wire up notifications
    # TODO: Implement notification wiring
    # - Listen to approval engine events → broadcast resource://approvals/pending updates
    # - Listen to agent loop state changes → broadcast resource://agents/{id}/state updates

    async def _on_approval_change(agent_id: str):
        """Approval engine notification handler."""
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/pending")
        await server.broadcast_resource_updated("resource://approvals/pending")

    async def _on_agent_state_change(agent_id: str):
        """Agent loop state change notification handler."""
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/state")

    # Hook up listeners for all agents
    for agent_id in registry.known_agents():
        try:
            infra = await registry.get_infrastructure(agent_id)
            # TODO: Add approval engine listener
            # infra.approval_engine.add_listener(lambda: _on_approval_change(agent_id))

            # Only add agent loop listener for local agents (no hasattr)
            if registry.get_agent_mode(agent_id) == AgentMode.LOCAL:
                local_runtime = registry.get_local_runtime(agent_id)
                if local_runtime and local_runtime.agent:
                    # TODO: Add agent state listener
                    # local_runtime.agent.add_state_listener(lambda: _on_agent_state_change(agent_id))
                    pass
        except Exception as e:
            logger.warning(f"Failed to hook listeners for {agent_id}: {e}")

    return server
