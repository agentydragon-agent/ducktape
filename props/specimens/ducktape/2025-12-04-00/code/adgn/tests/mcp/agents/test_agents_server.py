"""MCP tests for agents management server.

Tests agents://list resource and agent lifecycle via MCP tools.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from fastmcp.client import Client
from fastmcp.mcp_config import MCPConfig
from mcp.types import TextContent
import pytest

from adgn.agent.mcp_bridge.agents import AgentInfo, make_agents_server
from adgn.agent.persist import AgentMetadata


@pytest.fixture
def mock_registry(sqlite_persistence):
    """Create a mock registry for testing agents server.

    Uses real persistence for data storage, but mocks the agent container tracking.
    """
    registry = MagicMock()
    registry.persistence = sqlite_persistence
    registry.list_agents.return_value = []
    registry.is_external.return_value = False
    return registry


@pytest.fixture
def agents_server(mock_registry):
    """Create agents MCP server with mock registry."""
    return make_agents_server("agents", mock_registry)


class TestAgentsListResource:
    """Tests for agents://list resource."""

    @pytest.mark.asyncio
    async def test_list_agents_empty(self, agents_server, mock_registry):
        """agents://list returns empty list when no agents."""
        mock_registry.list_agents.return_value = []

        async with Client(agents_server) as sess:
            resources = await sess.list_resources()
            # Should have agents://list and agents://presets
            uris = [str(r.uri) for r in resources]
            assert "agents://list" in uris
            assert "agents://presets" in uris

            # Read the list resource
            contents = await sess.read_resource("agents://list")
            assert contents is not None
            # Content should be a list (empty)
            text_parts = [c for c in contents if isinstance(c, TextContent)]
            assert len(text_parts) >= 1
            # Validate structure - should be JSON list
            data = json.loads(text_parts[0].text)
            assert isinstance(data, list)
            assert len(data) == 0

    @pytest.mark.asyncio
    async def test_list_agents_with_running_agent(self, agents_server, mock_registry, sqlite_persistence):
        """agents://list returns running agent info."""
        # Create agent record in persistence first
        agent_id = await sqlite_persistence.create_agent(
            mcp_config=MCPConfig(mcpServers={}), metadata=AgentMetadata(preset="default")
        )

        # Setup mock container
        mock_container = MagicMock()
        mock_container.agent_id = agent_id
        mock_registry.list_agents.return_value = [mock_container]
        mock_registry.is_external.return_value = False

        async with Client(agents_server) as sess:
            contents = await sess.read_resource("agents://list")
            data = json.loads(contents[0].text)
            assert len(data) == 1
            agent = AgentInfo.model_validate(data[0])
            assert agent.id == agent_id
            assert agent.preset == "default"
            assert agent.booted is True
            assert agent.external is False

    @pytest.mark.asyncio
    async def test_list_agents_shows_persisted_not_booted(self, agents_server, mock_registry, sqlite_persistence):
        """agents://list shows persisted agents that aren't booted."""
        mock_registry.list_agents.return_value = []

        # Create agent record in persistence
        agent_id = await sqlite_persistence.create_agent(
            mcp_config=MCPConfig(mcpServers={}), metadata=AgentMetadata(preset="my-preset")
        )

        async with Client(agents_server) as sess:
            contents = await sess.read_resource("agents://list")
            data = json.loads(contents[0].text)
            assert len(data) == 1
            agent = AgentInfo.model_validate(data[0])
            assert agent.id == agent_id
            assert agent.preset == "my-preset"
            assert agent.booted is False

    @pytest.mark.asyncio
    async def test_list_agents_external_flag(self, agents_server, mock_registry, sqlite_persistence):
        """agents://list correctly marks external agents."""
        # Create agent record in persistence
        agent_id = await sqlite_persistence.create_agent(
            mcp_config=MCPConfig(mcpServers={}), metadata=AgentMetadata(preset="external")
        )

        mock_container = MagicMock()
        mock_container.agent_id = agent_id
        mock_registry.list_agents.return_value = [mock_container]
        mock_registry.is_external.return_value = True

        async with Client(agents_server) as sess:
            contents = await sess.read_resource("agents://list")
            data = json.loads(contents[0].text)
            assert len(data) == 1
            agent = AgentInfo.model_validate(data[0])
            assert agent.id == agent_id
            assert agent.external is True


class TestAgentsPresetsResource:
    """Tests for agents://presets resource."""

    @pytest.mark.asyncio
    async def test_list_presets(self, agents_server):
        """agents://presets returns available presets."""
        async with Client(agents_server) as sess:
            contents = await sess.read_resource("agents://presets")
            data = json.loads(contents[0].text)
            assert isinstance(data, list)
            # Should have at least the default preset
            names = [p["name"] for p in data]
            assert "default" in names
