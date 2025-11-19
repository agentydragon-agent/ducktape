"""Tests for agents MCP server resources and tools."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json

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

    # Global mailbox returns ReadResourceResult with multiple content blocks
    assert isinstance(result, mcp_types.ReadResourceResult)
    assert result.contents == []


@pytest.mark.asyncio
async def test_global_approvals_pending_multi_content(agents_client, mock_approval_hub):
    """Test resource://approvals/pending returns multi-content blocks."""
    # Add pending approvals to the hub
    tool_call_1 = ToolCall(name="test_tool_1", call_id="call-123", args_json='{"arg1": "value1"}')
    tool_call_2 = ToolCall(name="test_tool_2", call_id="call-456", args_json='{"arg2": "value2"}')

    mock_approval_hub._requests["call-123"] = ApprovalRequest(tool_call=tool_call_1)
    mock_approval_hub._requests["call-456"] = ApprovalRequest(tool_call=tool_call_2)

    result = await agents_client.read_resource("resource://approvals/pending")

    # Should return ReadResourceResult with multiple content blocks
    assert isinstance(result, mcp_types.ReadResourceResult)
    assert len(result.contents) == 4  # 2 approvals per agent x 2 agents

    # Each content block should be TextResourceContents with unique URI
    for content in result.contents:
        assert isinstance(content, mcp_types.TextResourceContents)
        assert content.mimeType == "application/json"
        assert content.uri.startswith("resource://agents/")
        assert "/approvals/" in content.uri

        # Parse and validate JSON
        data = json.loads(content.text)
        assert "agent_id" in data
        assert "call_id" in data
        assert "tool" in data
        assert "args" in data
        assert "timestamp" in data


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
    assert result.isError is False

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
    assert result.isError is False

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
    assert result.isError is False

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
    assert result.isError is False


@pytest.mark.asyncio
async def test_reject_nonexistent_call_id(agents_client):
    """Test reject_tool_call with non-existent call_id (no-op)."""
    # Call reject for non-existent call_id
    result = await agents_client.call_tool(
        "reject_tool_call", arguments={"agent_id": "local-agent", "call_id": "nonexistent", "reason": "test"}
    )

    # Should succeed (no-op)
    assert result.isError is False
