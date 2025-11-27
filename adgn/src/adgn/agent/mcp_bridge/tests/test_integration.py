"""Integration tests for mcp_bridge module.

Tests the Phase 5 two-compositor architecture components:
- InfrastructureRegistry
- TokenRoutingASGI
- agents management server
- agent_control server
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from adgn.agent.mcp_bridge.auth import load_tokens


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


class TestAgentsServer:
    """Tests for agents management server."""

    @pytest.mark.asyncio
    async def test_make_agents_server_creates_server(self):
        """make_agents_server creates a FastMCP server."""
        from adgn.agent.mcp_bridge.servers.agents import make_agents_server

        # Create mock registry
        mock_registry = MagicMock()
        mock_registry.list_agents.return_value = []
        mock_registry.persistence = AsyncMock()
        mock_registry.persistence.list_agents = AsyncMock(return_value=[])

        server = make_agents_server("test-agents", mock_registry)

        assert server is not None
        assert server.name == "test-agents"


class TestAgentControlServer:
    """Tests for agent_control server."""

    @pytest.mark.asyncio
    async def test_make_agent_control_server_creates_server(self):
        """make_agent_control_server creates a FastMCP server."""
        from adgn.agent.mcp_bridge.servers.agent_control import make_agent_control_server

        # Create mock container
        mock_container = MagicMock()
        mock_container.session = None

        server = make_agent_control_server("test-control", mock_container)

        assert server is not None
        assert server.name == "test-control"
