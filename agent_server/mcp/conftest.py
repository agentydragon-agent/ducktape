"""Conftest for agent_server/mcp tests."""

import pytest

# Import compositor fixture
from mcp_infra.testing.fixtures import compositor  # noqa: F401


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-asyncio auto mode."""
    config.option.asyncio_mode = "auto"
