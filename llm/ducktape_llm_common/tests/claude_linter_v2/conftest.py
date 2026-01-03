"""Shared fixtures for claude_linter_v2 tests."""

from pathlib import Path

import pytest

from ducktape_llm_common.claude_linter_v2.types import parse_session_id

# Synthetic file path for tests that need a path but don't create real files
TEST_FILE = Path("/test/file.py")


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Isolate tests from real user data and each other."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))


@pytest.fixture
def session_id():
    """Create a test session ID using all-zeros UUID."""
    return parse_session_id("00000000-0000-0000-0000-000000000000")
