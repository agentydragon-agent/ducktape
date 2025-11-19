"""Tests for agents MCP server resources and tools."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from unittest.mock import Mock

from fastmcp.client import Client
from mcp import types as mcp_types
import pytest

from adgn.agent.approvals import ApprovalRequest
from adgn.agent.handler import AbortTurnDecision, ContinueDecision
from adgn.agent.mcp_bridge.servers.agents import make_agents_server
from adgn.agent.mcp_bridge.types import AgentID
from adgn.agent.persist import ApprovalOutcome, Decision, PolicyProposal, ToolCall, ToolCallRecord


def read_text_json(result):
    """Helper to parse JSON from MCP resource result."""
    # FastMCP client returns a list of TextResourceContents
    if isinstance(result, list) and len(result) > 0:
        # Get the first content item and parse its text field
        text_content = result[0].text if hasattr(result[0], "text") else result[0]
        return json.loads(text_content) if isinstance(text_content, str) else text_content
    # Or it might be a dict-like object
    return result

# --- Test-specific fixtures ---
# Shared fixtures (mock_persistence, mock_approval_hub, mock_approval_engine,
# mock_running_infrastructure, mock_local_runtime, mock_registry) are in conftest.py


@pytest.fixture
async def agents_client(mock_registry):
    """Create agents server client."""
    server = await make_agents_server(mock_registry)
    async with Client(server) as client:
        yield client


# --- Resource Tests ---


@pytest.mark.asyncio
async def test_list_agents_resource(agents_client):
    """Test resource://agents/list returns all agents with capabilities."""
    result = await agents_client.read_resource("resource://agents/list")
    content = read_text_json(result)

    assert "agents" in content
    agents = content["agents"]
    assert len(agents) == 2

    # Check local agent
    local = next((a for a in agents if a["agent_id"] == "local-agent"), None)
    assert local is not None
    assert local["mode"] == "local"
    assert local["capabilities"]["chat"] is True
    assert local["capabilities"]["agent_loop"] is True
    assert local["state_uri"] == "resource://agents/local-agent/state"
    assert local["approvals_uri"] == "resource://agents/local-agent/approvals/pending"
    assert local["policy_proposals_uri"] == "resource://agents/local-agent/policy/proposals"

    # Check bridge agent
    bridge = next((a for a in agents if a["agent_id"] == "bridge-agent"), None)
    assert bridge is not None
    assert bridge["mode"] == "bridge"
    assert bridge["capabilities"]["chat"] is False
    assert bridge["capabilities"]["agent_loop"] is False
    assert bridge["state_uri"] is None
    assert bridge["approvals_uri"] == "resource://agents/bridge-agent/approvals/pending"
    assert bridge["policy_proposals_uri"] == "resource://agents/bridge-agent/policy/proposals"


@pytest.mark.asyncio
async def test_agent_state_resource_returns_snapshot(agents_client, mock_local_runtime):
    """Test resource://agents/{id}/state returns sampling snapshot for local agents."""
    result = await agents_client.read_resource("resource://agents/local-agent/state")
    content = read_text_json(result)

    # Verify sampling snapshot structure
    assert "ts" in content
    assert "servers" in content
    assert content["ts"] == "2025-01-15T10:00:00Z"
    assert content["servers"] == {}

    # Verify compositor.sampling_snapshot was called
    mock_local_runtime.running.compositor.sampling_snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_agent_state_resource_bridge_agent(agents_client):
    """Test resource://agents/{id}/state fails for bridge agents."""
    with pytest.raises(Exception, match=r"(?i)not a local agent"):
        await agents_client.read_resource("resource://agents/bridge-agent/state")


@pytest.mark.asyncio
async def test_agent_state_resource_with_servers(agents_client, mock_local_runtime):
    """Test resource://agents/{id}/state returns sampling snapshot with server data."""
    from adgn.mcp.snapshots import RunningServerEntry, SamplingSnapshot
    from mcp import types as mcp_types

    # Create a more complex sampling snapshot with running server
    server_entry = RunningServerEntry(
        state="running",
        initialize=mcp_types.InitializeResult(
            protocolVersion="2024-11-05",
            capabilities=mcp_types.ServerCapabilities(tools={"listChanged": True}),
            serverInfo=mcp_types.Implementation(name="test-server", version="1.0.0"),
        ),
        tools=[
            mcp_types.Tool(
                name="test_tool",
                description="A test tool",
                inputSchema={"type": "object", "properties": {}},
            )
        ],
    )

    sampling_snapshot = SamplingSnapshot(
        ts="2025-01-15T10:30:00Z", servers={"test-server": server_entry}
    )

    mock_local_runtime.running.compositor.sampling_snapshot.return_value = sampling_snapshot

    result = await agents_client.read_resource("resource://agents/local-agent/state")
    content = read_text_json(result)

    # Verify sampling snapshot structure
    assert content["ts"] == "2025-01-15T10:30:00Z"
    assert "test-server" in content["servers"]

    server = content["servers"]["test-server"]
    assert server["state"] == "running"
    assert "initialize" in server
    assert "tools" in server
    assert len(server["tools"]) == 1
    assert server["tools"][0]["name"] == "test_tool"


@pytest.mark.asyncio
async def test_agent_state_resource_no_runtime(mock_registry, agents_client):
    """Test resource://agents/{id}/state fails when local agent has no runtime."""

    # Mock get_local_runtime to return None for local-agent
    original_get_runtime = mock_registry.get_local_runtime

    def get_runtime_none(agent_id):
        if agent_id == "local-agent":
            return None
        return original_get_runtime(agent_id)

    mock_registry.get_local_runtime = get_runtime_none

    with pytest.raises(Exception, match=r"(?i)no local runtime"):
        await agents_client.read_resource("resource://agents/local-agent/state")


@pytest.mark.asyncio
async def test_agent_approvals_pending_empty(agents_client):
    """Test resource://agents/{id}/approvals/pending with no pending approvals."""
    result = await agents_client.read_resource("resource://agents/local-agent/approvals/pending")
    content = read_text_json(result)

    assert content["agent_id"] == "local-agent"
    assert content["pending"] == []


@pytest.mark.asyncio
async def test_agent_approvals_pending_with_items(agents_client, mock_approval_hub):
    """Test resource://agents/{id}/approvals/pending with pending approvals."""
    # Add pending approval
    tool_call = ToolCall(name="test_tool", call_id="call-123", args_json='{"arg1": "value1"}')
    request = ApprovalRequest(tool_call=tool_call)
    mock_approval_hub._requests["call-123"] = request

    result = await agents_client.read_resource("resource://agents/local-agent/approvals/pending")
    content = read_text_json(result)

    assert content["agent_id"] == "local-agent"
    assert len(content["pending"]) == 1

    approval = content["pending"][0]
    assert approval["call_id"] == "call-123"
    assert approval["tool"] == "test_tool"
    assert approval["args"] == {"arg1": "value1"}
    assert "timestamp" in approval


@pytest.mark.asyncio
async def test_global_approvals_pending_empty(agents_client):
    """Test resource://approvals/pending with no pending approvals."""
    result = await agents_client.read_resource("resource://approvals/pending")

    # FastMCP wraps ReadResourceResult in a list of TextResourceContents
    assert isinstance(result, list)
    assert len(result) == 1

    # Parse the wrapped result
    wrapped = result[0]
    assert isinstance(wrapped, mcp_types.TextResourceContents)
    data = json.loads(wrapped.text)
    assert data["contents"] == []


@pytest.mark.asyncio
async def test_global_approvals_pending_multi_content(agents_client, mock_approval_hub):
    """Test resource://approvals/pending returns multi-content blocks."""
    # Add pending approvals to the hub
    tool_call_1 = ToolCall(name="test_tool_1", call_id="call-123", args_json='{"arg1": "value1"}')
    tool_call_2 = ToolCall(name="test_tool_2", call_id="call-456", args_json='{"arg2": "value2"}')

    mock_approval_hub._requests["call-123"] = ApprovalRequest(tool_call=tool_call_1)
    mock_approval_hub._requests["call-456"] = ApprovalRequest(tool_call=tool_call_2)

    result = await agents_client.read_resource("resource://approvals/pending")

    # FastMCP wraps ReadResourceResult in a list of TextResourceContents
    assert isinstance(result, list)
    assert len(result) == 1

    # Parse the wrapped result
    wrapped = result[0]
    assert isinstance(wrapped, mcp_types.TextResourceContents)
    data = json.loads(wrapped.text)

    # Should have multiple content blocks (2 approvals per agent x 2 agents)
    contents = data["contents"]
    assert len(contents) == 4

    # Each content block should be TextResourceContents with unique URI
    for content in contents:
        assert content["mimeType"] == "application/json"
        assert content["uri"].startswith("resource://agents/")
        assert "/approvals/" in content["uri"]

        # Parse and validate JSON
        approval_data = json.loads(content["text"])
        assert "agent_id" in approval_data
        assert "call_id" in approval_data
        assert "tool" in approval_data
        assert "args" in approval_data
        assert "timestamp" in approval_data


@pytest.mark.asyncio
async def test_agent_approvals_history_empty(agents_client, mock_persistence):
    """Test resource://agents/{id}/approvals/history with no history."""
    mock_persistence.list_tool_calls.return_value = []

    result = await agents_client.read_resource("resource://agents/local-agent/approvals/history")
    content = read_text_json(result)

    assert content["agent_id"] == "local-agent"
    assert content["timeline"] == []
    assert content["pending"] == []
    assert content["count"] == 0


@pytest.mark.asyncio
async def test_agent_approvals_history_with_records(agents_client, mock_persistence):
    """Test resource://agents/{id}/approvals/history with completed records."""
    # Create completed tool call record
    decided_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
    record = ToolCallRecord(
        call_id="call-123",
        run_id="run-456",
        agent_id=AgentID("local-agent"),
        tool_call=ToolCall(name="test_tool", call_id="call-123", args_json='{"arg1": "value1"}'),
        decision=Decision(outcome=ApprovalOutcome.USER_APPROVE, decided_at=decided_at, reason=None),
        execution=None,
    )

    mock_persistence.list_tool_calls.return_value = [record]

    result = await agents_client.read_resource("resource://agents/local-agent/approvals/history")
    content = read_text_json(result)

    assert content["agent_id"] == "local-agent"
    assert len(content["timeline"]) == 1
    assert content["count"] == 1

    entry = content["timeline"][0]
    assert entry["call_id"] == "call-123"
    assert entry["tool"] == "test_tool"
    assert entry["args"] == {"arg1": "value1"}
    assert entry["outcome"] == "user_approve"


@pytest.mark.asyncio
async def test_agent_approvals_history_filters_pending(agents_client, mock_persistence):
    """Test resource://agents/{id}/approvals/history filters out pending records."""
    # Create pending record (no decision)
    pending_record = ToolCallRecord(
        call_id="call-pending",
        run_id="run-456",
        agent_id=AgentID("local-agent"),
        tool_call=ToolCall(name="pending_tool", call_id="call-pending", args_json="{}"),
        decision=None,
        execution=None,
    )

    # Create completed record
    decided_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
    completed_record = ToolCallRecord(
        call_id="call-completed",
        run_id="run-456",
        agent_id=AgentID("local-agent"),
        tool_call=ToolCall(name="completed_tool", call_id="call-completed", args_json="{}"),
        decision=Decision(outcome=ApprovalOutcome.USER_APPROVE, decided_at=decided_at, reason=None),
        execution=None,
    )

    mock_persistence.list_tool_calls.return_value = [pending_record, completed_record]

    result = await agents_client.read_resource("resource://agents/local-agent/approvals/history")
    content = read_text_json(result)

    # Only completed record should be in timeline
    assert len(content["timeline"]) == 1
    assert content["timeline"][0]["call_id"] == "call-completed"


@pytest.mark.asyncio
async def test_agent_policy_proposals_empty(agents_client, mock_persistence):
    """Test resource://agents/{id}/policy/proposals with no proposals."""
    mock_persistence.list_policy_proposals.return_value = []

    result = await agents_client.read_resource("resource://agents/local-agent/policy/proposals")
    content = read_text_json(result)

    assert content["agent_id"] == "local-agent"
    assert content["proposals"] == []
    assert content["active_policy_uri"] == "resource://approval-policy/policy.py"


@pytest.mark.asyncio
async def test_agent_policy_proposals_with_items(agents_client, mock_persistence):
    """Test resource://agents/{id}/policy/proposals with proposals."""
    created_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    decided_at = datetime(2025, 1, 15, 11, 0, 0, tzinfo=UTC)

    proposal = PolicyProposal(
        id="prop-123", status="approved", created_at=created_at, decided_at=decided_at, content="policy content"
    )

    mock_persistence.list_policy_proposals.return_value = [proposal]

    result = await agents_client.read_resource("resource://agents/local-agent/policy/proposals")
    content = read_text_json(result)

    assert content["agent_id"] == "local-agent"
    assert len(content["proposals"]) == 1

    prop = content["proposals"][0]
    assert prop["id"] == "prop-123"
    assert prop["status"] == "approved"
    assert prop["proposal_uri"] == "resource://approval-policy/proposals/prop-123"


# --- Error Cases ---


@pytest.mark.asyncio
async def test_agent_not_found(agents_client):
    """Test accessing resources for non-existent agent."""
    with pytest.raises(Exception, match=r"(?i)not found"):
        await agents_client.read_resource("resource://agents/nonexistent-agent/approvals/pending")


@pytest.mark.asyncio
async def test_agent_not_initialized(mock_registry, agents_client):
    """Test accessing resources for agent that exists but isn't initialized."""

    # Add uninitialized agent to registry
    def get_infrastructure_uninitialized(agent_id: AgentID):
        if agent_id == "uninitialized-agent":
            raise KeyError(f"Agent {agent_id} infrastructure not yet initialized")
        # Call original for other agents
        raise KeyError(f"Agent {agent_id} not found in registry")

    mock_registry.get_infrastructure = get_infrastructure_uninitialized

    # Add to known_agents
    original_known = mock_registry.known_agents
    mock_registry.known_agents = lambda: [*original_known(), "uninitialized-agent"]

    with pytest.raises(Exception, match=r"(?i)not yet initialized"):
        await agents_client.read_resource("resource://agents/uninitialized-agent/approvals/pending")


# --- Tool Tests ---


@pytest.mark.asyncio
async def test_approve_tool_call(agents_client, mock_approval_hub):
    """Test approve_tool_call resolves with ContinueDecision."""
    # Setup pending approval
    tool_call = ToolCall(name="test_tool", call_id="call-123", args_json="{}")
    request = ApprovalRequest(tool_call=tool_call)

    # Create future for the approval
    fut = asyncio.get_running_loop().create_future()
    mock_approval_hub._futures["call-123"] = fut
    mock_approval_hub._requests["call-123"] = request

    # Call approve tool
    result = await agents_client.call_tool(
        "approve_tool_call", arguments={"agent_id": "local-agent", "call_id": "call-123"}
    )

    # Should succeed
    assert result.is_error is False

    # Check that the future was resolved with ContinueDecision
    assert fut.done()
    decision = fut.result()
    assert isinstance(decision, ContinueDecision)

    # Approval should be removed from pending
    assert "call-123" not in mock_approval_hub._requests


@pytest.mark.asyncio
async def test_reject_tool_call(agents_client, mock_approval_hub):
    """Test reject_tool_call resolves with AbortTurnDecision."""
    # Setup pending approval
    tool_call = ToolCall(name="test_tool", call_id="call-456", args_json="{}")
    request = ApprovalRequest(tool_call=tool_call)

    # Create future for the approval
    fut = asyncio.get_running_loop().create_future()
    mock_approval_hub._futures["call-456"] = fut
    mock_approval_hub._requests["call-456"] = request

    # Call reject tool
    result = await agents_client.call_tool(
        "reject_tool_call", arguments={"agent_id": "local-agent", "call_id": "call-456", "reason": "Test rejection"}
    )

    # Should succeed
    assert result.is_error is False

    # Check that the future was resolved with AbortTurnDecision
    assert fut.done()
    decision = fut.result()
    assert isinstance(decision, AbortTurnDecision)
    assert decision.reason == "Test rejection"

    # Approval should be removed from pending
    assert "call-456" not in mock_approval_hub._requests


@pytest.mark.asyncio
async def test_abort_agent_local(agents_client, mock_local_runtime):
    """Test abort_agent succeeds for local agents."""
    result = await agents_client.call_tool("abort_agent", arguments={"agent_id": "local-agent"})

    # Should succeed
    assert result.is_error is False

    # Verify agent.abort() was called
    mock_local_runtime.agent.abort.assert_called_once()


@pytest.mark.asyncio
async def test_abort_agent_bridge_fails(agents_client):
    """Test abort_agent fails for bridge agents."""
    with pytest.raises(Exception, match=r"(?i)(not a local agent|cannot abort)"):
        await agents_client.call_tool("abort_agent", arguments={"agent_id": "bridge-agent"})


@pytest.mark.asyncio
async def test_abort_agent_not_found(agents_client):
    """Test abort_agent fails for non-existent agent."""
    with pytest.raises(Exception, match=r"(?i)not found"):
        await agents_client.call_tool("abort_agent", arguments={"agent_id": "nonexistent-agent"})


@pytest.mark.asyncio
async def test_abort_agent_no_runtime(mock_registry, agents_client):
    """Test abort_agent fails for local agent without runtime."""

    # Mock get_local_runtime to return None for local-agent
    original_get_runtime = mock_registry.get_local_runtime

    def get_runtime_none(agent_id: AgentID):
        if agent_id == "local-agent":
            return None
        return original_get_runtime(agent_id)

    mock_registry.get_local_runtime = get_runtime_none

    with pytest.raises(Exception, match=r"(?i)no agent loop"):
        await agents_client.call_tool("abort_agent", arguments={"agent_id": "local-agent"})


# --- Tool Error Cases ---


@pytest.mark.asyncio
async def test_approve_nonexistent_call_id(agents_client):
    """Test approve_tool_call with non-existent call_id (no-op)."""
    # Call approve for non-existent call_id
    result = await agents_client.call_tool(
        "approve_tool_call", arguments={"agent_id": "local-agent", "call_id": "nonexistent"}
    )

    # Should succeed (no-op)
    assert result.is_error is False


@pytest.mark.asyncio
async def test_reject_nonexistent_call_id(agents_client):
    """Test reject_tool_call with non-existent call_id (no-op)."""
    # Call reject for non-existent call_id
    result = await agents_client.call_tool(
        "reject_tool_call", arguments={"agent_id": "local-agent", "call_id": "nonexistent", "reason": "test"}
    )

    # Should succeed (no-op)
    assert result.is_error is False


# --- Additional Test Coverage ---


@pytest.mark.asyncio
async def test_global_approvals_pending_different_per_agent(mock_persistence, mock_approval_engine):
    """Test resource://approvals/pending returns different approvals per agent."""
    from adgn.agent.approvals import ApprovalHub

    # Create separate approval hubs for each agent
    local_hub = ApprovalHub()
    bridge_hub = ApprovalHub()

    # Create separate infrastructures
    local_infra = Mock()
    local_infra.approval_hub = local_hub
    local_infra.approval_engine = mock_approval_engine

    bridge_infra = Mock()
    bridge_infra.approval_hub = bridge_hub
    bridge_infra.approval_engine = mock_approval_engine

    # Create a custom registry with separate infrastructures
    custom_registry = Mock()

    def known_agents():
        return [AgentID("local-agent"), AgentID("bridge-agent")]

    async def get_infrastructure(agent_id: AgentID):
        if agent_id == AgentID("local-agent"):
            return local_infra
        elif agent_id == AgentID("bridge-agent"):
            return bridge_infra
        raise KeyError(f"Agent {agent_id} not found")

    def get_agent_mode(agent_id: AgentID):
        from adgn.agent.mcp_bridge.types import AgentMode

        return AgentMode.LOCAL if agent_id == "local-agent" else AgentMode.BRIDGE

    custom_registry.known_agents = known_agents
    custom_registry.get_infrastructure = get_infrastructure
    custom_registry.get_agent_mode = get_agent_mode

    # Create server with custom registry
    server = await make_agents_server(custom_registry)

    # Add different pending approvals to each agent
    tool_call_local_1 = ToolCall(name="local_tool_1", call_id="local-call-1", args_json='{"param": "value1"}')
    tool_call_local_2 = ToolCall(name="local_tool_2", call_id="local-call-2", args_json='{"param": "value2"}')
    tool_call_bridge_1 = ToolCall(name="bridge_tool_1", call_id="bridge-call-1", args_json='{"param": "value3"}')

    local_hub._requests["local-call-1"] = ApprovalRequest(tool_call=tool_call_local_1)
    local_hub._requests["local-call-2"] = ApprovalRequest(tool_call=tool_call_local_2)
    bridge_hub._requests["bridge-call-1"] = ApprovalRequest(tool_call=tool_call_bridge_1)

    async with Client(server) as client:
        result = await client.read_resource("resource://approvals/pending")

        # FastMCP wraps ReadResourceResult in a list of TextResourceContents
        assert isinstance(result, list)
        assert len(result) == 1

        # Parse the wrapped result
        wrapped = result[0]
        assert isinstance(wrapped, mcp_types.TextResourceContents)
        data = json.loads(wrapped.text)

        # Should have multiple content blocks (3 total: 2 from local-agent + 1 from bridge-agent)
        contents = data["contents"]
        assert len(contents) == 3

        # Parse all content blocks and verify agent_id, call_id, and tool are correct
        approvals_by_agent = {"local-agent": [], "bridge-agent": []}
        for content in contents:
            approval_data = json.loads(content["text"])

            agent_id = approval_data["agent_id"]
            call_id = approval_data["call_id"]
            tool = approval_data["tool"]

            approvals_by_agent[agent_id].append({"call_id": call_id, "tool": tool})

        # Verify local-agent has 2 approvals
        assert len(approvals_by_agent["local-agent"]) == 2
        local_calls = {a["call_id"] for a in approvals_by_agent["local-agent"]}
        assert "local-call-1" in local_calls
        assert "local-call-2" in local_calls

        # Verify bridge-agent has 1 approval
        assert len(approvals_by_agent["bridge-agent"]) == 1
        bridge_calls = {a["call_id"] for a in approvals_by_agent["bridge-agent"]}
        assert "bridge-call-1" in bridge_calls


@pytest.mark.asyncio
async def test_agent_approvals_history_mixed_outcomes(agents_client, mock_persistence):
    """Test resource://agents/{id}/approvals/history with mixed decision outcomes."""
    from datetime import timedelta

    base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

    # Create tool call records with different outcomes
    records = [
        # POLICY_ALLOW
        ToolCallRecord(
            call_id="call-policy-allow",
            run_id="run-1",
            agent_id=AgentID("local-agent"),
            tool_call=ToolCall(name="safe_tool", call_id="call-policy-allow", args_json='{"action": "read"}'),
            decision=Decision(outcome=ApprovalOutcome.POLICY_ALLOW, decided_at=base_time, reason="Auto-approved"),
            execution=None,
        ),
        # USER_APPROVE
        ToolCallRecord(
            call_id="call-user-approve",
            run_id="run-1",
            agent_id=AgentID("local-agent"),
            tool_call=ToolCall(name="user_tool", call_id="call-user-approve", args_json='{"action": "write"}'),
            decision=Decision(
                outcome=ApprovalOutcome.USER_APPROVE, decided_at=base_time + timedelta(minutes=1), reason=None
            ),
            execution=None,
        ),
        # POLICY_DENY_CONTINUE
        ToolCallRecord(
            call_id="call-policy-deny-cont",
            run_id="run-1",
            agent_id=AgentID("local-agent"),
            tool_call=ToolCall(
                name="risky_tool", call_id="call-policy-deny-cont", args_json='{"action": "delete"}'
            ),
            decision=Decision(
                outcome=ApprovalOutcome.POLICY_DENY_CONTINUE,
                decided_at=base_time + timedelta(minutes=2),
                reason="Denied by policy",
            ),
            execution=None,
        ),
        # USER_DENY_ABORT
        ToolCallRecord(
            call_id="call-user-deny-abort",
            run_id="run-1",
            agent_id=AgentID("local-agent"),
            tool_call=ToolCall(
                name="dangerous_tool", call_id="call-user-deny-abort", args_json='{"action": "destroy"}'
            ),
            decision=Decision(
                outcome=ApprovalOutcome.USER_DENY_ABORT,
                decided_at=base_time + timedelta(minutes=3),
                reason="User rejected",
            ),
            execution=None,
        ),
    ]

    mock_persistence.list_tool_calls.return_value = records

    result = await agents_client.read_resource("resource://agents/local-agent/approvals/history")
    content = read_text_json(result)

    assert content["agent_id"] == "local-agent"
    assert len(content["timeline"]) == 4
    assert content["count"] == 4

    # Verify all outcomes are present
    outcomes_in_timeline = {entry["outcome"] for entry in content["timeline"]}
    assert ApprovalOutcome.POLICY_ALLOW in outcomes_in_timeline
    assert ApprovalOutcome.USER_APPROVE in outcomes_in_timeline
    assert ApprovalOutcome.POLICY_DENY_CONTINUE in outcomes_in_timeline
    assert ApprovalOutcome.USER_DENY_ABORT in outcomes_in_timeline

    # Verify specific entries
    policy_allow_entry = next(e for e in content["timeline"] if e["call_id"] == "call-policy-allow")
    assert policy_allow_entry["outcome"] == "policy_allow"
    assert policy_allow_entry["tool"] == "safe_tool"
    assert policy_allow_entry["reason"] == "Auto-approved"

    user_deny_entry = next(e for e in content["timeline"] if e["call_id"] == "call-user-deny-abort")
    assert user_deny_entry["outcome"] == "user_deny_abort"
    assert user_deny_entry["tool"] == "dangerous_tool"
    assert user_deny_entry["reason"] == "User rejected"


@pytest.mark.asyncio
async def test_agent_state_resource_idle_agent(agents_client, mock_local_runtime):
    """Test resource://agents/{id}/state for an idle agent (no active sampling)."""
    from adgn.mcp.snapshots import SamplingSnapshot

    # Mock an idle snapshot (empty servers, older timestamp)
    idle_snapshot = SamplingSnapshot(ts="2025-01-15T09:00:00Z", servers={})

    mock_local_runtime.running.compositor.sampling_snapshot.return_value = idle_snapshot

    result = await agents_client.read_resource("resource://agents/local-agent/state")
    content = read_text_json(result)

    # Verify idle snapshot structure
    assert content["ts"] == "2025-01-15T09:00:00Z"
    assert content["servers"] == {}

    # Verify sampling_snapshot was called
    mock_local_runtime.running.compositor.sampling_snapshot.assert_called()


@pytest.mark.asyncio
async def test_global_approvals_pending_ordering(agents_client, mock_approval_hub):
    """Test resource://approvals/pending maintains agent and approval ordering."""
    # Add multiple pending approvals in specific order
    for i in range(3):
        tool_call = ToolCall(name=f"tool_{i}", call_id=f"call-{i}", args_json=f'{{"index": {i}}}')
        mock_approval_hub._requests[f"call-{i}"] = ApprovalRequest(tool_call=tool_call)

    result = await agents_client.read_resource("resource://approvals/pending")

    # FastMCP wraps ReadResourceResult in a list of TextResourceContents
    assert isinstance(result, list)
    assert len(result) == 1

    # Parse the wrapped result
    wrapped = result[0]
    assert isinstance(wrapped, mcp_types.TextResourceContents)
    data = json.loads(wrapped.text)

    # Each agent should have 3 approvals (6 total for 2 agents)
    contents = data["contents"]
    assert len(contents) == 6

    # Parse and verify ordering within each agent
    for content in contents:
        approval_data = json.loads(content["text"])
        assert "agent_id" in approval_data
        assert "call_id" in approval_data
        assert "tool" in approval_data
