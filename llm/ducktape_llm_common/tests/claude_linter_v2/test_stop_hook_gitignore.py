"""Test that stop hook respects gitignore."""

import subprocess

import pytest
from hamcrest import all_of, assert_that, contains_string, has_entries

from ducktape_llm_common.claude_code_api import StopRequest
from ducktape_llm_common.claude_linter_v2.hooks.handler import HookHandler
from ducktape_llm_common.claude_linter_v2.types import parse_session_id


@pytest.fixture
def handler():
    """Create a hook handler instance."""
    handler = HookHandler()
    # Ensure quality gate is enabled for testing
    handler.config_loader.config.hooks["stop"].quality_gate = True
    return handler


@pytest.fixture
def session_id():
    """Create a test session ID."""
    return parse_session_id("12345678-1234-5678-1234-567812345678")


def test_stop_hook_respects_gitignore(handler, session_id, tmp_path, monkeypatch):
    """Test that stop hook respects gitignore and doesn't scan node_modules."""
    # Change to tmp directory using pytest's monkeypatch
    monkeypatch.chdir(tmp_path)

    # Initialize git repo
    subprocess.run(["git", "init"], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], check=True)

    # Create .gitignore
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\nvenv/\n__pycache__/\n*.pyc\n")

    # Create a tracked Python file with violations
    tracked_file = tmp_path / "app.py"
    tracked_file.write_text(
        """
try:
    something()
except:  # Bare except
    pass
"""
    )

    # Create an ignored Python file with violations
    node_modules = tmp_path / "node_modules" / "some_package"
    node_modules.mkdir(parents=True)
    ignored_file = node_modules / "bad_code.py"
    ignored_file.write_text(
        """
try:
    something()
except:  # Many bare excepts
    pass

try:
    other()
except:
    pass
"""
    )

    # Create another ignored file in venv
    venv = tmp_path / "venv" / "lib"
    venv.mkdir(parents=True)
    venv_file = venv / "library.py"
    venv_file.write_text(
        """
def bad():
    try:
        x = 1
    except:
        pass
"""
    )

    # Add and commit the tracked file (not the ignored ones)
    subprocess.run(["git", "add", ".gitignore", "app.py"], check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], check=True)

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should block due to errors in tracked file only
    response_dict = result.model_dump()

    # Check main keys and verify reason contains tracked filename and violation snippets
    assert_that(
        response_dict,
        has_entries(
            continue_=True,
            stopReason=None,
            suppressOutput=None,
            decision="block",
            reason=all_of(contains_string(str(tracked_file)), contains_string("Do not use bare `except`")),
        ),
    )


def test_stop_hook_fallback_when_not_git_repo(handler, session_id, tmp_path, monkeypatch):
    """Test that stop hook falls back to all files when not in a git repo."""
    # Change to tmp directory using pytest's monkeypatch
    monkeypatch.chdir(tmp_path)

    # Don't initialize git - just create files

    # Create a Python file with violations
    bad_file = tmp_path / "bad_code.py"
    bad_file.write_text(
        """
try:
    something()
except:  # Bare except
    pass
"""
    )

    # Create node_modules (would be ignored if git was present)
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    node_file = node_modules / "package.py"
    node_file.write_text(
        """
try:
    x = 1
except:
    pass
"""
    )

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should find violations in all files (no git = no gitignore)
    response_dict = result.model_dump()

    # Both files have bare-except violations; check keys and that reason mentions both files and ruff message
    assert_that(
        response_dict,
        has_entries(
            continue_=True,
            stopReason=None,
            suppressOutput=None,
            decision="block",
            reason=all_of(
                contains_string(str(bad_file)),
                contains_string(str(node_file)),
                contains_string("Do not use bare `except`"),
            ),
        ),
    )
