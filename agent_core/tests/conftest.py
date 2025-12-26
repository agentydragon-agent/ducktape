"""Pytest configuration for agent_core tests."""

from __future__ import annotations

import pytest

# Register testing fixtures:
# - agent_core.testing.fixtures: Core agent fixtures (recording_handler, make_test_agent, etc.)
# - mcp_infra.testing.fixtures: MCP compositor fixtures (compositor, compositor_client, etc.)
pytest_plugins = ["agent_core.testing.fixtures", "mcp_infra.testing.fixtures", "pytest_asyncio"]


@pytest.fixture
def text_content():
    """Helper to create MCP TextContent blocks."""
    from mcp import types as mcp_types

    return lambda text: mcp_types.TextContent(type="text", text=text)
