"""Integration tests for mcp_bridge module.

Tests the Phase 5 two-compositor architecture components:
- InfrastructureRegistry
- TokenRoutingASGI
- agents management server
- agent_control server
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp.mcp_config import MCPConfig
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from adgn.agent.mcp_bridge.auth import TokenRoutingASGI, load_tokens
from adgn.agent.mcp_bridge.registry import InfrastructureRegistry
from adgn.agent.mcp_bridge.servers.agent_control import make_agent_control_server
from adgn.agent.mcp_bridge.servers.agents import make_agents_server

# ---------------------------------------------------------------------------
# Shared Fixtures
# ---------------------------------------------------------------------------
# Note: sqlite_persistence and docker_client fixtures come from tests/conftest.py


@pytest.fixture
def mock_compositor():
    """Create mock compositor for verifying mount/unmount calls."""
    compositor = AsyncMock()
    compositor.mount_inproc = AsyncMock()
    compositor.unmount_server = AsyncMock()
    return compositor


@pytest.fixture
def mock_container():
    """Create mock agent container for verifying close calls."""
    container = MagicMock()
    container.agent_id = "test-agent-1"
    container._compositor = MagicMock()
    container.session = None  # For agent_control tests
    container.close = AsyncMock()
    return container


@pytest.fixture
def mock_registry(sqlite_persistence):
    """Create mock infrastructure registry using real persistence."""
    registry = MagicMock()
    registry.list_agents.return_value = []
    registry.persistence = sqlite_persistence
    return registry


@pytest.fixture
def user_app():
    """Create a simple user-facing ASGI app for routing tests."""

    async def homepage(request):
        return PlainTextResponse("user-app")

    return Starlette(routes=[Route("/", homepage)])


@pytest.fixture
def agent_app_factory():
    """Factory to create agent ASGI apps that identify themselves."""

    def make_app(agent_id: str):
        async def homepage(request):
            return PlainTextResponse(f"agent-{agent_id}")

        return Starlette(routes=[Route("/", homepage)])

    return make_app


@pytest.fixture
def registry_factory(sqlite_persistence):
    """Factory to create InfrastructureRegistry with real persistence.

    Uses mock Docker client since Docker may not be available in test environments.
    """

    def make_registry(**kwargs):
        return InfrastructureRegistry(
            persistence=kwargs.get("persistence", sqlite_persistence),
            model="test-model",
            client_factory=lambda m: MagicMock(),
            docker_client=kwargs.get("docker_client", MagicMock()),
            mcp_config=MCPConfig(mcpServers={}),
            **{k: v for k, v in kwargs.items() if k not in ("persistence", "docker_client")},
        )

    return make_registry


# ---------------------------------------------------------------------------
# Token Loading Tests
# ---------------------------------------------------------------------------


class TestLoadTokens:
    """Tests for token loading."""

    def test_load_tokens_missing_file(self):
        """Returns empty tokens when config file doesn't exist."""
        user_tokens, agent_tokens = load_tokens(Path("/nonexistent/path.yaml"))
        assert user_tokens == {}
        assert agent_tokens == {}

    def test_load_tokens_from_file(self, tmp_path: Path):
        """Loads tokens from YAML file."""
        config = tmp_path / "tokens.yaml"
        config.write_text("""
users:
  admin: "admin-token-123"
  viewer: "viewer-token-456"

agents:
  claude-code-1: "agent-token-aaa"
  external-agent: "agent-token-bbb"
""")
        user_tokens, agent_tokens = load_tokens(config)

        # User tokens: token -> user_id
        assert user_tokens == {
            "admin-token-123": "admin",
            "viewer-token-456": "viewer",
        }

        # Agent tokens: token -> agent_id
        assert agent_tokens == {
            "agent-token-aaa": "claude-code-1",
            "agent-token-bbb": "external-agent",
        }

    def test_load_tokens_empty_file(self, tmp_path: Path):
        """Returns empty tokens when config file is empty."""
        config = tmp_path / "tokens.yaml"
        config.write_text("")
        user_tokens, agent_tokens = load_tokens(config)
        assert user_tokens == {}
        assert agent_tokens == {}

    def test_load_tokens_null_values_skipped(self, tmp_path: Path):
        """Skips null token values in config."""
        config = tmp_path / "tokens.yaml"
        config.write_text("""
users:
  admin: "valid-token"
  invalid: null
  empty: ""
""")
        user_tokens, agent_tokens = load_tokens(config)
        # Only non-null, non-empty tokens should be included
        assert user_tokens == {"valid-token": "admin"}
        assert agent_tokens == {}


# ---------------------------------------------------------------------------
# Token Routing Tests
# ---------------------------------------------------------------------------


class TestTokenRoutingASGI:
    """Tests for TokenRoutingASGI ASGI router."""

    def test_routes_user_token_to_user_app(self, user_app, agent_app_factory):
        """User tokens route to user compositor app."""
        router = TokenRoutingASGI(
            user_tokens={"user-token-123": "admin"},
            agent_tokens={"agent-token-abc": "agent-1"},
            user_app=user_app,
            agent_apps={"agent-1": agent_app_factory("1")},
        )

        client = TestClient(router)
        response = client.get("/", headers={"Authorization": "Bearer user-token-123"})
        assert response.status_code == 200
        assert response.text == "user-app"

    def test_routes_agent_token_to_agent_app(self, user_app, agent_app_factory):
        """Agent tokens route to their specific agent compositor app."""
        router = TokenRoutingASGI(
            user_tokens={"user-token-123": "admin"},
            agent_tokens={"agent-token-abc": "agent-1", "agent-token-xyz": "agent-2"},
            user_app=user_app,
            agent_apps={
                "agent-1": agent_app_factory("1"),
                "agent-2": agent_app_factory("2"),
            },
        )

        client = TestClient(router)

        # First agent
        response = client.get("/", headers={"Authorization": "Bearer agent-token-abc"})
        assert response.status_code == 200
        assert response.text == "agent-1"

        # Second agent
        response = client.get("/", headers={"Authorization": "Bearer agent-token-xyz"})
        assert response.status_code == 200
        assert response.text == "agent-2"

    def test_returns_401_without_token(self, user_app):
        """Returns 401 when no Authorization header is present."""
        router = TokenRoutingASGI(
            user_tokens={"token": "user"},
            agent_tokens={},
            user_app=user_app,
            agent_apps={},
        )

        client = TestClient(router, raise_server_exceptions=False)
        response = client.get("/")
        assert response.status_code == 401
        assert "Bearer token required" in response.text

    def test_returns_401_without_bearer_prefix(self, user_app):
        """Returns 401 when Authorization header doesn't use Bearer scheme."""
        router = TokenRoutingASGI(
            user_tokens={"token": "user"},
            agent_tokens={},
            user_app=user_app,
            agent_apps={},
        )

        client = TestClient(router, raise_server_exceptions=False)
        response = client.get("/", headers={"Authorization": "Basic token"})
        assert response.status_code == 401
        assert "Bearer token required" in response.text

    def test_returns_401_for_invalid_token(self, user_app):
        """Returns 401 when token is not recognized."""
        router = TokenRoutingASGI(
            user_tokens={"valid-token": "user"},
            agent_tokens={},
            user_app=user_app,
            agent_apps={},
        )

        client = TestClient(router, raise_server_exceptions=False)
        response = client.get("/", headers={"Authorization": "Bearer invalid-token"})
        assert response.status_code == 401
        assert "Invalid token" in response.text

    def test_returns_404_when_agent_app_not_found(self, user_app):
        """Returns 404 when agent token is valid but agent app isn't registered."""
        router = TokenRoutingASGI(
            user_tokens={},
            agent_tokens={"agent-token": "agent-1"},
            user_app=user_app,
            agent_apps={},  # Empty - no agent apps registered
        )

        client = TestClient(router, raise_server_exceptions=False)
        response = client.get("/", headers={"Authorization": "Bearer agent-token"})
        assert response.status_code == 404
        assert "Agent not found" in response.text


# ---------------------------------------------------------------------------
# MCP Server Creation Tests
# ---------------------------------------------------------------------------


class TestAgentsServer:
    """Tests for agents management server."""

    @pytest.mark.asyncio
    async def test_make_agents_server_creates_server(self, mock_registry):
        """make_agents_server creates a FastMCP server."""
        server = make_agents_server("test-agents", mock_registry)

        assert server is not None
        assert server.name == "test-agents"


class TestAgentControlServer:
    """Tests for agent_control server."""

    @pytest.mark.asyncio
    async def test_make_agent_control_server_creates_server(self, mock_container):
        """make_agent_control_server creates a FastMCP server."""
        server = make_agent_control_server("test-control", mock_container)

        assert server is not None
        assert server.name == "test-control"


# ---------------------------------------------------------------------------
# Infrastructure Registry Tests
# ---------------------------------------------------------------------------


class TestInfrastructureRegistry:
    """Tests for InfrastructureRegistry agent lifecycle management."""

    def test_get_agent_returns_none_for_unknown(self, registry_factory):
        """get_agent returns None for unknown agent."""
        registry = registry_factory()
        assert registry.get_agent("unknown-id") is None

    def test_list_agents_empty_initially(self, registry_factory):
        """list_agents returns empty list initially."""
        registry = registry_factory()
        assert registry.list_agents() == []

    def test_is_external_false_for_unknown(self, registry_factory):
        """is_external returns False for unknown agent."""
        registry = registry_factory()
        assert registry.is_external("unknown-id") is False

    @pytest.mark.asyncio
    async def test_shutdown_agent_no_op_for_unknown(self, registry_factory):
        """shutdown_agent does nothing for unknown agent."""
        registry = registry_factory()
        # Should not raise
        await registry.shutdown_agent("unknown-id")

    @pytest.mark.asyncio
    async def test_shutdown_agent_closes_container(self, registry_factory, mock_container, mock_compositor):
        """shutdown_agent closes container and unmounts from compositor."""
        registry = registry_factory()
        registry.global_compositor = mock_compositor
        registry._agents["test-agent-1"] = mock_container

        await registry.shutdown_agent("test-agent-1")

        mock_container.close.assert_awaited_once()
        mock_compositor.unmount_server.assert_awaited_once_with("agent_test-agent-1")
        assert "test-agent-1" not in registry._agents

    @pytest.mark.asyncio
    async def test_shutdown_agent_cleans_up_external_tracking(self, registry_factory, mock_container, mock_compositor):
        """shutdown_agent removes agent from external tracking set."""
        registry = registry_factory()
        registry.global_compositor = mock_compositor
        registry._agents["test-agent-1"] = mock_container
        registry._external_agents.add("test-agent-1")

        assert registry.is_external("test-agent-1") is True

        await registry.shutdown_agent("test-agent-1")

        assert registry.is_external("test-agent-1") is False

    @pytest.mark.asyncio
    async def test_shutdown_all_shuts_down_all_agents(self, registry_factory, mock_compositor):
        """shutdown_all shuts down all registered agents."""
        registry = registry_factory()
        registry.global_compositor = mock_compositor

        # Add multiple mock containers
        container1 = MagicMock()
        container1.agent_id = "agent-1"
        container1._compositor = MagicMock()
        container1.close = AsyncMock()

        container2 = MagicMock()
        container2.agent_id = "agent-2"
        container2._compositor = MagicMock()
        container2.close = AsyncMock()

        registry._agents["agent-1"] = container1
        registry._agents["agent-2"] = container2

        await registry.shutdown_all()

        container1.close.assert_awaited_once()
        container2.close.assert_awaited_once()
        assert len(registry._agents) == 0

    @pytest.mark.asyncio
    async def test_boot_agent_returns_existing_if_already_booted(self, registry_factory, mock_container):
        """boot_agent returns existing container if already booted."""
        registry = registry_factory()
        registry._agents["test-agent-1"] = mock_container

        result = await registry.boot_agent("test-agent-1")

        assert result is mock_container

    @pytest.mark.asyncio
    async def test_boot_agent_raises_for_unknown_agent(self, registry_factory):
        """boot_agent raises KeyError if agent not in DB (using real persistence)."""
        registry = registry_factory()

        with pytest.raises(KeyError, match="Agent not found"):
            await registry.boot_agent("nonexistent-agent")

    @pytest.mark.asyncio
    async def test_create_external_agent_returns_existing_if_already_created(self, registry_factory, mock_container):
        """create_external_agent returns existing container if already exists."""
        registry = registry_factory()
        registry._agents["test-agent-1"] = mock_container

        result = await registry.create_external_agent("test-agent-1")

        assert result is mock_container

    @pytest.mark.asyncio
    async def test_create_external_agent_marks_as_external(self, registry_factory, mock_compositor):
        """create_external_agent marks agent as external."""
        registry = registry_factory()
        registry.global_compositor = mock_compositor

        # Patch build_container to return a mock
        with patch("adgn.agent.mcp_bridge.registry.build_container") as mock_build:
            container = MagicMock()
            container.agent_id = "external-agent"
            container._compositor = MagicMock()
            mock_build.return_value = container

            await registry.create_external_agent("external-agent")

            assert registry.is_external("external-agent") is True
            assert "external-agent" in registry._agents
