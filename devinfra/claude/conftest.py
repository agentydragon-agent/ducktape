"""Pytest configuration for claude tests."""

from pathlib import Path
from unittest.mock import patch

import pytest

from devinfra.claude.settings import HookSettings


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-asyncio auto mode."""
    config.option.asyncio_mode = "auto"


@pytest.fixture
def hook_settings(tmp_path: Path) -> HookSettings:
    """Minimal HookSettings for tests that don't need supervisor/proxy infrastructure."""
    return HookSettings(session_dir=tmp_path / "session")


@pytest.fixture
def patch_credentials_path(tmp_path: Path):
    """Patch CREDENTIALS_PATH to a custom path for testing."""
    path = tmp_path / "credentials.json"
    with patch("devinfra.claude.claude_api.credentials.CREDENTIALS_PATH", path):
        yield path


@pytest.fixture
def no_credentials(tmp_path: Path):
    """Patch CREDENTIALS_PATH to a nonexistent file (no cached credentials)."""
    with patch("devinfra.claude.claude_api.credentials.CREDENTIALS_PATH", tmp_path / "nonexistent"):
        yield


@pytest.fixture
def no_usage_cache(tmp_path: Path):
    """Patch CACHE_PATH to a nonexistent file (no cached usage)."""
    with patch("devinfra.claude.usage_cache.CACHE_PATH", tmp_path / "nonexistent"):
        yield
