"""Shared fixtures for example scripts tests."""

from unittest.mock import patch

import pytest


@pytest.fixture
def mock_agent_setup():
    """Mock setup_agent_database for example scripts.

    Test database is already initialized via test_db/synced_test_db fixtures,
    so we mock the setup call to avoid re-initialization.
    """
    with patch("adgn.props.agent_helpers.setup_agent_database"):
        yield
