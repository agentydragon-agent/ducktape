"""Unified cross-agent management MCP server.

Provides resources and tools for managing multiple agents from a single connection.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from fastmcp.mcp_config import MCPConfig, MCPServerTypes
from mcp import types as mcp_types
from pydantic import BaseModel, TypeAdapter

from adgn.agent.approvals import ApprovalRequest
from adgn.agent.handler import AbortTurnDecision, ContinueDecision
from adgn.agent.mcp_bridge import resources
from adgn.agent.mcp_bridge.types import AgentID, AgentMode
from adgn.agent.persist import ApprovalOutcome, ToolCallRecord
from adgn.agent.server.agents_ws import AgentBrief
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.approval_policy.server import ApproveProposalArgs, RejectProposalArgs, SetPolicyTextArgs
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

    # Parse args from JSON
    args = json.loads(record.tool_call.args_json) if record.tool_call.args_json else {}

    return ApprovalHistoryEntry(
        call_id=record.call_id,
        tool=record.tool_call.name,
        args=args,
        outcome=record.decision.outcome,
        reason=record.decision.reason,
        timestamp=record.decision.decided_at,
    )


# Enumerations
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


class DenyToolCallArgs(BaseModel):
    """Arguments for deny_tool_call tool (semantic alias for reject_tool_call)."""

    agent_id: AgentID
    call_id: str
    reason: str


class DenyAbortArgs(BaseModel):
    """Arguments for deny_abort tool."""

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
    outcome: ApprovalOutcome
    reason: str | None = None
    timestamp: datetime


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


class AgentInfoDetailed(BaseModel):
    """Basic agent metadata NOT available from other MCP resources.

    For additional data, query the specific MCP resources:
    - Compositor state: resource://agents/{id}/snapshot
    - Policy: resource://approval-policy/policy.py (per-agent server)
    - Approvals: resource://agents/{id}/approvals/pending, resource://agents/{id}/approvals/history
    """

    agent_id: AgentID
    mode: AgentMode
    model: str | None = None  # Model name for local agents
    status: str  # "running" or "stopped"


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
        resources.AGENTS_LIST,
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

            state_uri = resources.agent_state(agent_id) if is_local else None
            approvals_uri = resources.agent_approvals_pending(agent_id)
            policy_proposals_uri = resources.agent_policy_proposals(agent_id)

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

        # Get sampling snapshot from the compositor
        return await local_runtime.running.compositor.sampling_snapshot()

    @server.resource(
        "resource://agents/{agent_id}/snapshot",
        name="agent.snapshot",
        mime_type="application/json",
        description="Full compositor sampling snapshot for a local agent",
    )
    async def agent_snapshot(agent_id: AgentID):
        """Get full compositor sampling snapshot for an agent.

        Returns the complete compositor sampling state including tools, resources,
        and prompts from all mounted servers.

        Raises ValueError if agent is not local or has no runtime.
        """
        if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {agent_id} is not a local agent")

        local_runtime = registry.get_local_runtime(agent_id)
        if local_runtime is None:
            raise ValueError(f"Agent {agent_id} has no local runtime")

        # Delegate to compositor's sampling_snapshot()
        return await local_runtime.running.compositor.sampling_snapshot()

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
        resources.APPROVALS_PENDING_GLOBAL,
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
                approval_uri = resources.agent_approval(agent_id, approval.call_id)
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
                proposal_uri=resources.policy_proposal(p.id),
            )
            for p in proposals
        ]

        return AgentPolicyProposals(
            agent_id=agent_id, proposals=proposal_infos, active_policy_uri=resources.ACTIVE_POLICY
        )

    @server.resource(
        "resource://agents/{agent_id}/info",
        name="agent.info",
        mime_type="application/json",
        description="Basic agent metadata (mode, model, status) - use specific resources for details",
    )
    async def agent_info(agent_id: AgentID) -> AgentInfoDetailed:
        """Get basic agent metadata NOT available from other MCP resources.

        Returns only agent mode, model, and runtime status.
        For additional data, query the appropriate MCP resources:
        - Compositor: resource://agents/{id}/snapshot
        - Policy: resource://approval-policy/policy.py (per-agent server)
        - Approvals: resource://agents/{id}/approvals/pending, resource://agents/{id}/approvals/history
        """
        mode = registry.get_agent_mode(agent_id)

        # Determine model and status
        model: str | None = None
        status = "stopped"

        local_runtime = registry.get_local_runtime(agent_id)
        if local_runtime is not None:
            model = local_runtime.model
            status = "running"

        return AgentInfoDetailed(
            agent_id=agent_id,
            mode=mode,
            model=model,
            status=status,
        )

    # Tools

    @server.tool()
    async def approve_tool_call(agent_id: str, call_id: str) -> None:
        infra = await registry.get_infrastructure(AgentID(agent_id))
        infra.approval_hub.resolve(call_id, ContinueDecision())

        await server.broadcast_resource_updated(resources.agent_approvals_pending(agent_id))
        await server.broadcast_resource_updated(resources.agent_approvals_history(agent_id))
        await server.broadcast_resource_updated(resources.APPROVALS_PENDING_GLOBAL)

    @server.tool()
    async def reject_tool_call(agent_id: str, call_id: str, reason: str) -> None:
        infra = await registry.get_infrastructure(AgentID(agent_id))
        infra.approval_hub.resolve(call_id, AbortTurnDecision(reason=reason))

        await server.broadcast_resource_updated(resources.agent_approvals_pending(agent_id))
        await server.broadcast_resource_updated(resources.agent_approvals_history(agent_id))
        await server.broadcast_resource_updated(resources.APPROVALS_PENDING_GLOBAL)

    @server.tool()
    async def deny_tool_call(agent_id: AgentID, call_id: str, reason: str) -> SimpleOk:
        """Deny/reject a pending tool call approval (semantic alias for reject_tool_call).

        Provides a clearer semantic for denial operations alongside approve/reject terminology.
        """
        # Delegate to reject_tool_call
        await reject_tool_call(str(agent_id), call_id, reason)
        return SimpleOk(ok=True)

    @server.tool()
    async def deny_abort(agent_id: AgentID, call_id: str, reason: str) -> SimpleOk:
        """Deny an abort request via the approval policy server.

        Routes the denial to the approval_policy_admin server's reject_proposal tool.
        Provides a semantic alternative for denying abort-related approval proposals.
        """
        infra = await registry.get_infrastructure(agent_id)
        client = infra.compositor.get_child_client("approval_policy_admin")
        await client.call_tool("reject_proposal", {"id": call_id, "reason": reason})

        await server.broadcast_resource_updated(resources.agent_approvals_pending(str(agent_id)))
        await server.broadcast_resource_updated(resources.agent_approvals_history(str(agent_id)))
        await server.broadcast_resource_updated(resources.APPROVALS_PENDING_GLOBAL)
        return SimpleOk(ok=True)

    @server.tool()
    async def abort_agent(agent_id: AgentID) -> None:
        """Raises ValueError if agent is not local or has no agent loop."""
        if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {agent_id} is not a local agent (cannot abort)")

        local_runtime = registry.get_local_runtime(agent_id)
        if local_runtime is None or local_runtime.agent is None:
            raise ValueError(f"Agent {agent_id} has no agent loop")

        await local_runtime.agent.abort()  # type: ignore[attr-defined]  # TODO: Implement abort() on MiniCodex

    @server.tool()
    async def prompt(agent_id: AgentID, message: str) -> SimpleOk:
        """Send a user message to an agent (via chat.human server).

        Routes the message to the agent's chat.human MCP server by calling
        the post tool. Returns immediately after queueing the message.

        Args:
            agent_id: The target agent ID.
            message: The user message to send.

        Returns:
            SimpleOk indicating successful message delivery.
        """
        infra = await registry.get_infrastructure(agent_id)
        client = infra.compositor.get_child_client("chat.human")
        await client.call_tool("post", {"message": message})
        return SimpleOk(ok=True)

    @server.tool()
    async def abort_run(agent_id: AgentID) -> SimpleOk:
        """Abort a running agent (alias for abort_agent).

        Requests immediate termination of the agent's active loop.
        This is a semantic alias for abort_agent that returns SimpleOk for consistency.

        Args:
            agent_id: The target agent ID.

        Returns:
            SimpleOk indicating successful abort request.

        Raises:
            ValueError: If agent is not local or has no agent loop.
        """
        await abort_agent(agent_id)
        return SimpleOk(ok=True)

    @server.tool()
    async def update_mcp_config(agent_id: AgentID, config: dict) -> SimpleOk:
        """Update MCP server configuration for an agent.

        Converges agent's MCP mounts to exactly match the provided configuration
        (full replacement: unmounts servers not in config, mounts new servers).
        """
        infra = await registry.get_infrastructure(agent_id)
        cfg = MCPConfig.model_validate(config)
        await infra.compositor.reconfigure(cfg)
        return SimpleOk(ok=True)

    @server.tool()
    async def attach_server(agent_id: AgentID, name: str, spec: dict) -> SimpleOk:
        """Attach a new MCP server to an agent.

        Mounts a single MCP server with the given name and specification.
        Raises ValueError if a server with that name is already mounted.
        """
        infra = await registry.get_infrastructure(agent_id)
        server_spec = TypeAdapter(MCPServerTypes).validate_python(spec)
        await infra.compositor.mount_server(name, server_spec)
        return SimpleOk(ok=True)

    @server.tool()
    async def detach_server(agent_id: AgentID, name: str) -> SimpleOk:
        """Detach an MCP server from an agent.

        Unmounts a single MCP server by name. Raises RuntimeError if the
        server is pinned (system servers cannot be unmounted).
        """
        infra = await registry.get_infrastructure(agent_id)
        await infra.compositor.unmount_server(name)
        return SimpleOk(ok=True)

    @server.tool()
    async def set_policy(agent_id: AgentID, policy_text: str) -> SimpleOk:
        """Set the active policy text for an agent.

        Directly sets the policy source code after validation via the
        approval policy admin server. The policy is self-checked before
        activation to ensure it's valid Python and can execute properly.

        Raises ValueError if agent not found.
        Raises RuntimeError if policy validation fails.
        """
        infra = await registry.get_infrastructure(agent_id)
        await infra.policy_approver.set_policy_text(SetPolicyTextArgs(source=policy_text))
        return SimpleOk(ok=True)

    @server.tool()
    async def approve_proposal(agent_id: AgentID, proposal_id: str) -> SimpleOk:
        """Approve a pending policy proposal for an agent.

        Approves a policy proposal by ID, which activates the proposed
        policy as the agent's active policy. The proposal must be in
        PENDING status.

        Raises ValueError if agent or proposal not found.
        Raises RuntimeError if proposal is not in PENDING status.
        """
        infra = await registry.get_infrastructure(agent_id)
        await infra.policy_approver.approve_proposal(ApproveProposalArgs(id=proposal_id))
        return SimpleOk(ok=True)

    @server.tool()
    async def reject_proposal(agent_id: AgentID, proposal_id: str, reason: str) -> SimpleOk:
        """Reject a pending policy proposal for an agent.

        Rejects a policy proposal by ID with an optional reason. The
        proposal must be in PENDING status. The proposal remains in the
        database but is marked as rejected.

        Raises ValueError if agent or proposal not found.
        Raises RuntimeError if proposal is not in PENDING status.
        """
        infra = await registry.get_infrastructure(agent_id)
        await infra.policy_approver.reject_proposal(RejectProposalArgs(id=proposal_id, reason=reason))
        return SimpleOk(ok=True)

    @server.tool()
    async def create_agent(preset: str, system_message: str | None = None) -> AgentBrief:
        """Create a new agent with the given preset and optional system message.

        Generates a unique agent ID and initializes infrastructure for a new agent.
        The agent will be ready to accept connections and process requests.

        Args:
            preset: Agent preset name/configuration identifier.
            system_message: Optional system message override for the agent.

        Returns:
            AgentBrief with the newly created agent's ID and initial state.
        """
        # Generate unique agent ID
        agent_id = AgentID(f"agent-{uuid4().hex[:8]}")

        # Create infrastructure for the agent
        await registry.create_agent(agent_id)

        # Return agent brief with the created agent's ID
        return AgentBrief(id=agent_id)

    @server.tool()
    async def delete_agent(agent_id: AgentID) -> SimpleOk:
        """Delete an agent and clean up its infrastructure.

        Removes the agent from the registry, closes all running infrastructure,
        and releases associated resources. The agent can no longer be accessed
        after deletion.

        Args:
            agent_id: ID of the agent to delete.

        Returns:
            SimpleOk confirming successful deletion.

        Raises:
            KeyError: If the agent is not found in the registry.
        """
        await registry.remove_agent(agent_id)
        return SimpleOk(ok=True)

    @server.tool()
    async def boot_agent(agent_id: AgentID) -> SimpleOk:
        """Ensure an agent is booted and its infrastructure is running.

        Creates or resumes the agent's infrastructure to ensure it's ready
        for operation. If the agent is already running, this is a no-op.

        Args:
            agent_id: ID of the agent to boot.

        Returns:
            SimpleOk confirming the agent is ready.

        Raises:
            KeyError: If the agent is not found in the registry.
        """
        await registry.ensure_live(agent_id)
        return SimpleOk(ok=True)

    # Wire up notifications
    # For approval changes: notifications are broadcast directly in approve/reject tools
    # (ApprovalHub doesn't have built-in notification system)
    # For policy changes: wire policy engine notifier to broadcast MCP resource updates

    for agent_id in registry.known_agents():
        infra = await registry.get_infrastructure(agent_id)

        # Closure captures agent_id for this specific agent
        def make_policy_notifier(aid: str):
            def notifier(uri: str):
                # Notifier is sync, schedule broadcast in event loop
                loop = asyncio.get_running_loop()
                _task = loop.create_task(server.broadcast_resource_updated(uri))
                # Don't await task - fire and forget notification
                _task.add_done_callback(
                    lambda t: logger.debug(f"Broadcast complete for {uri}")
                    if not t.exception()
                    else logger.warning(f"Broadcast failed for {uri}: {t.exception()}")
                )

            return notifier

        infra.approval_engine.set_notifier(make_policy_notifier(agent_id))

    return server
