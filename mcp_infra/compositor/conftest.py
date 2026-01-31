"""Fixtures for compositor tests."""

from __future__ import annotations

import pytest

from agent_core.testing.responses import reasoning_model
from mcp_infra.testing.docker_fixtures import docker_exec_server_py312slim

# Import fixtures from testing modules (replaces deprecated pytest_plugins)
from mcp_infra.testing.fixtures import *  # noqa: F403
from test_util.docker import python_slim_image


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-asyncio auto mode."""
    config.option.asyncio_mode = "auto"
