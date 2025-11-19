"""Test MCP Bridge with separated MCP server and Management UI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
from fastmcp.mcp_config import MCPConfig
import pytest

from adgn.agent.mcp_bridge.server import InfrastructureRegistry, create_management_ui_app, create_mcp_server_app
from adgn.agent.mcp_bridge.types import AgentID
from adgn.agent.persist.sqlite import SQLitePersistence
from adgn.agent.runtime.infrastructure import RunningInfrastructure

# temp_db fixture is provided by conftest.py


@pytest.fixture
def token_mapping_file(tmp_path: Path) -> Path:
    """Create token mapping file for multi-tenant testing."""
    tokens_file = tmp_path / "tokens.json"
    tokens_file.write_text(json.dumps({"test-token-1": "agent-1", "test-token-2": "agent-2"}), encoding="utf-8")
    return tokens_file


@pytest.fixture
async def infrastructure_registry(temp_db: Path, docker_client) -> InfrastructureRegistry:
    """Create infrastructure registry for testing."""
    persistence = SQLitePersistence(temp_db)
    await persistence.ensure_schema()

    return InfrastructureRegistry(
        persistence=persistence, docker_client=docker_client, mcp_config=MCPConfig(mcpServers={}), initial_policy=None
    )


async def test_mcp_server_requires_token_auth(
    token_mapping_file: Path, infrastructure_registry: InfrastructureRegistry
):
    """Test that MCP server requires token authentication."""
    mcp_app = await create_mcp_server_app(auth_tokens_path=token_mapping_file, registry=infrastructure_registry)

    client = TestClient(mcp_app)

    # Request without token should fail
    response = client.get("/sse")
    assert response.status_code == 403, "Should reject requests without token"

    # Request with invalid token should fail
    response = client.get("/sse", headers={"Authorization": "Bearer invalid-token"})
    assert response.status_code == 403, "Should reject requests with invalid token"

    # Request with valid token should succeed (might fail for other reasons, but auth passes)
    response = client.get("/sse", headers={"Authorization": "Bearer test-token-1"})
    assert response.status_code != 403, "Should accept valid token"


async def test_management_ui_requires_auth(infrastructure_registry: InfrastructureRegistry):
    """Test that management UI requires authentication."""
    ui_app, ui_token = await create_management_ui_app(registry=infrastructure_registry)

    client = TestClient(ui_app)

    # Health check should require auth
    response = client.get("/health")
    assert response.status_code == 401, "Health check should require auth"

    # Health check should work with valid token
    response = client.get("/health", headers={"Authorization": f"Bearer {ui_token}"})
    assert response.status_code == 200, "Health check should work with valid token"
    assert response.json() == {"status": "ok"}

    # API endpoints should require auth
    response = client.get("/api/agents")
    assert response.status_code == 401, "API should require auth"

    # API endpoints should work with valid token
    response = client.get("/api/agents", headers={"Authorization": f"Bearer {ui_token}"})
    assert response.status_code == 200, "API should work with valid token"


async def test_mcp_server_routes_to_agent_infrastructure(
    token_mapping_file: Path, infrastructure_registry: InfrastructureRegistry
):
    """Test that MCP server routes requests to correct agent infrastructure."""
    mcp_app = await create_mcp_server_app(auth_tokens_path=token_mapping_file, registry=infrastructure_registry)

    client = TestClient(mcp_app)

    # Make request with agent-1 token
    _ = client.get("/sse", headers={"Authorization": "Bearer test-token-1"})

    # Should create infrastructure for agent-1
    assert "agent-1" in infrastructure_registry._agents

    # Make request with agent-2 token
    _ = client.get("/sse", headers={"Authorization": "Bearer test-token-2"})

    # Should create infrastructure for agent-2
    assert "agent-2" in infrastructure_registry._agents


async def test_infrastructure_registry_caches_per_agent(infrastructure_registry: InfrastructureRegistry):
    """Test that infrastructure registry caches infrastructure per agent."""
    # Create infrastructure for agent-1
    running1, app1 = await infrastructure_registry.get_or_create_infrastructure(AgentID("agent-1"))

    # Get again - should return cached
    running1_cached, app1_cached = await infrastructure_registry.get_or_create_infrastructure(AgentID("agent-1"))

    assert running1 is running1_cached, "Should return cached infrastructure"
    assert app1 is app1_cached, "Should return cached app"

    # Create infrastructure for agent-2
    running2, app2 = await infrastructure_registry.get_or_create_infrastructure(AgentID("agent-2"))

    assert running2 is not running1, "Different agents should have different infrastructure"
    assert app2 is not app1, "Different agents should have different apps"


async def test_infrastructure_registry_get_nonexistent(infrastructure_registry: InfrastructureRegistry):
    """Test that get_running_infrastructure returns None for nonexistent agent."""
    result = infrastructure_registry.get_running_infrastructure(AgentID("nonexistent"))
    assert result is None, "Should return None for nonexistent agent"


async def test_management_ui_agents_endpoint_delegates_to_mcp_server(infrastructure_registry: InfrastructureRegistry):
    """Test that /api/agents endpoint delegates to agents MCP server."""
    # Register a local agent in the registry
    # Create mock infrastructure for a local agent
    mock_infra = Mock(spec=RunningInfrastructure)
    mock_infra.approval_hub = Mock()
    mock_infra.approval_hub.pending = {}
    mock_infra.approval_engine = Mock()
    mock_infra.approval_engine.persistence = Mock()
    mock_infra.approval_engine.persistence.list_tool_calls = AsyncMock(return_value=[])
    mock_infra.approval_engine.persistence.list_policy_proposals = AsyncMock(return_value=[])

    # Create mock local runtime
    mock_runtime = Mock()
    mock_runtime.agent = Mock()

    # Create mock compositor app
    mock_compositor_app = Mock()

    # Register the agent
    infrastructure_registry.register_local_agent(
        agent_id=AgentID("test-local-agent"),
        running=mock_infra,
        compositor_app=mock_compositor_app,
        local_runtime=mock_runtime,
    )

    # Create management UI app
    ui_app, ui_token = await create_management_ui_app(registry=infrastructure_registry)

    client = TestClient(ui_app)

    # Call /api/agents with valid token
    response = client.get("/api/agents", headers={"Authorization": f"Bearer {ui_token}"})
    assert response.status_code == 200, "API should work with valid token"

    # Verify response structure from agents MCP server
    data = response.json()
    assert "agents" in data, "Response should have 'agents' key"
    agents = data["agents"]
    assert isinstance(agents, list), "agents should be a list"

    # Find our test agent
    test_agent = next((a for a in agents if a["agent_id"] == "test-local-agent"), None)
    assert test_agent is not None, "test-local-agent should be in the list"

    # Verify agent properties
    assert test_agent["mode"] == "local", "Agent mode should be 'local'"
    assert test_agent["capabilities"]["chat"] is True, "Local agent should have chat capability"
    assert test_agent["capabilities"]["agent_loop"] is True, "Local agent should have agent_loop capability"
    assert test_agent["state_uri"] == "resource://agents/test-local-agent/state", "Should have state URI"
    assert test_agent["approvals_uri"] == "resource://agents/test-local-agent/approvals/pending", (
        "Should have approvals URI"
    )
    assert test_agent["policy_proposals_uri"] == "resource://agents/test-local-agent/policy/proposals", (
        "Should have policy proposals URI"
    )
