"""Test MCP Bridge with separated MCP server and Management UI."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from fastmcp.mcp_config import MCPConfig
import pytest

from adgn.agent.mcp_bridge.server import InfrastructureRegistry, create_management_ui_app, create_mcp_server_app
from adgn.agent.persist.sqlite import SQLitePersistence


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create temporary database path."""
    return tmp_path / "test.db"


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


async def test_management_ui_no_auth_required(infrastructure_registry: InfrastructureRegistry):
    """Test that management UI does not require authentication."""
    ui_app = await create_management_ui_app(registry=infrastructure_registry)

    client = TestClient(ui_app)

    # Health check should work without auth
    response = client.get("/health")
    assert response.status_code == 200, "Health check should not require auth"
    assert response.json() == {"status": "ok"}

    # API endpoints should work without auth
    response = client.get("/api/agents")
    assert response.status_code == 200, "API should not require auth"


async def test_mcp_server_routes_to_agent_infrastructure(
    token_mapping_file: Path, infrastructure_registry: InfrastructureRegistry
):
    """Test that MCP server routes requests to correct agent infrastructure."""
    mcp_app = await create_mcp_server_app(auth_tokens_path=token_mapping_file, registry=infrastructure_registry)

    client = TestClient(mcp_app)

    # Make request with agent-1 token
    _ = client.get("/sse", headers={"Authorization": "Bearer test-token-1"})

    # Should create infrastructure for agent-1
    assert "agent-1" in infrastructure_registry._infra_cache

    # Make request with agent-2 token
    _ = client.get("/sse", headers={"Authorization": "Bearer test-token-2"})

    # Should create infrastructure for agent-2
    assert "agent-2" in infrastructure_registry._infra_cache


async def test_websocket_channels_available_on_ui_server(infrastructure_registry: InfrastructureRegistry):
    """Test that WebSocket channels are available on management UI server."""
    ui_app = await create_management_ui_app(registry=infrastructure_registry)

    # Test that WebSocket endpoints exist (they'll reject without agent_id, but route exists)
    # Note: TestClient doesn't support WebSocket testing well, so we just check routes exist
    routes = [route.path for route in ui_app.routes if hasattr(route, "path")]

    assert "/ws/policy" in routes, "Policy channel should exist"
    assert "/ws/approvals" in routes, "Approvals channel should exist"
    assert "/ws/mcp" in routes, "MCP channel should exist"


async def test_infrastructure_registry_caches_per_agent(infrastructure_registry: InfrastructureRegistry):
    """Test that infrastructure registry caches infrastructure per agent."""
    # Create infrastructure for agent-1
    running1, app1 = await infrastructure_registry.get_or_create_infrastructure("agent-1")

    # Get again - should return cached
    running1_cached, app1_cached = await infrastructure_registry.get_or_create_infrastructure("agent-1")

    assert running1 is running1_cached, "Should return cached infrastructure"
    assert app1 is app1_cached, "Should return cached app"

    # Create infrastructure for agent-2
    running2, app2 = await infrastructure_registry.get_or_create_infrastructure("agent-2")

    assert running2 is not running1, "Different agents should have different infrastructure"
    assert app2 is not app1, "Different agents should have different apps"


async def test_infrastructure_registry_get_nonexistent(infrastructure_registry: InfrastructureRegistry):
    """Test that get_running_infrastructure returns None for nonexistent agent."""
    result = infrastructure_registry.get_running_infrastructure("nonexistent")
    assert result is None, "Should return None for nonexistent agent"
