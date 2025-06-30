"""Shared pytest configuration and fixtures for ducktape_llm_common tests."""

import tempfile
from pathlib import Path

import pygit2
import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_git_repo(temp_dir):
    """Create a temporary git repository for tests."""
    # Initialize git repo using pygit2
    repo = pygit2.init_repository(str(temp_dir), bare=False)

    # Set git config
    config = repo.config
    config["user.email"] = "test@example.com"
    config["user.name"] = "Test User"

    return temp_dir
