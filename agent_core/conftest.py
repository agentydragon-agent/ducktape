"""Pytest configuration for agent_core tests."""

from __future__ import annotations

import pytest

from agent_core.agent import Agent
from agent_core.loop_control import AllowAnyToolOrTextMessage
from agent_core.mcp_provider import MCPToolProvider
from agent_core.tool_provider import TextContent
from agent_core_testing.openai_mock import NoopOpenAIClient

# Register testing fixtures:
# - agent_core_testing.fixtures: Core agent fixtures (recording_handler, make_test_agent, etc.)
# - agent_core_testing.responses: Response factories and step runner fixtures
# - mcp_infra.testing.fixtures: MCP compositor fixtures (compositor, compositor_client, etc.)
pytest_plugins = [
    "agent_core_testing.fixtures",
    "agent_core_testing.responses",
    "mcp_infra.testing.fixtures",
    "pytest_asyncio",
]


@pytest.fixture
def text_content():
    """Helper to create TextContent blocks."""
    return lambda text: TextContent(text=text)


@pytest.fixture
async def noop_agent(compositor_client, recording_handler):
    """Agent with NoopOpenAIClient for testing message processing without sampling."""
    tool_provider = MCPToolProvider(compositor_client)
    return await Agent.create(
        tool_provider=tool_provider,
        client=NoopOpenAIClient(),
        handlers=[recording_handler],
        tool_policy=AllowAnyToolOrTextMessage(),
    )
