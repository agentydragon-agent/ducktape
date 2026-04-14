"""Shared pytest config for grocy_mcp tests."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.option.asyncio_mode = "auto"
