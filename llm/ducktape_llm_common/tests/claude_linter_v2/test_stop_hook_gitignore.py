"""Test that stop hook respects gitignore."""

import os
import subprocess
from pathlib import Path

import pytest

from ducktape_llm_common.claude_linter_v2.hooks.handler import HookHandler
from ducktape_llm_common.claude_linter_v2.hooks.requests import StopRequest
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


def test_stop_hook_respects_gitignore(handler, session_id, tmp_path):
    """Test that stop hook respects gitignore and doesn't scan node_modules."""
    # Change to tmp directory
    original_cwd = Path.cwd()
    os.chdir(tmp_path)

    try:
        # Initialize git repo
        subprocess.run(["git", "init"], check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], check=True)

        # Create .gitignore
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\nvenv/\n__pycache__/\n*.pyc\n")

        # Create a tracked Python file with violations
        tracked_file = tmp_path / "app.py"
        tracked_file.write_text("""
try:
    something()
except:  # Bare except
    pass
""")

        # Create an ignored Python file with violations
        node_modules = tmp_path / "node_modules" / "some_package"
        node_modules.mkdir(parents=True)
        ignored_file = node_modules / "bad_code.py"
        ignored_file.write_text("""
try:
    something()
except:  # Many bare excepts
    pass

try:
    other()
except:
    pass
""")

        # Create another ignored file in venv
        venv = tmp_path / "venv" / "lib"
        venv.mkdir(parents=True)
        venv_file = venv / "library.py"
        venv_file.write_text("""
def bad():
    try:
        x = 1
    except:
        pass
""")

        # Add and commit the tracked file (not the ignored ones)
        subprocess.run(["git", "add", ".gitignore", "app.py"], check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], check=True)

        # Create stop hook request
        request = StopRequest(
            hook_event_name="Stop",
            session_id=str(session_id),
        )

        # Handle the hook
        result = handler.handle("Stop", request)

        # Should block due to errors in tracked file only
        response_dict = result.model_dump()

        # The exact response should have 2 violations on line 4:
        # 1. From AST checker: "Bare except clause is not allowed. Use specific exception types. [bare_except]"
        # 2. From ruff: "Do not use bare `except` [ruff:E722]"
        assert response_dict == {
            "continue_": True,
            "stopReason": None,
            "suppressOutput": None,
            "decision": "block",
            "reason": f"Code has 2 errors that must be fixed:\n{tracked_file}:  Line 4: Bare except clause is not allowed. Use specific exception types. [bare_except]  Line 4: Do not use bare `except` [ruff:E722]\n\nCommand to check all violations:  cl2 check {tracked_file}",
        }

    finally:
        os.chdir(original_cwd)


def test_stop_hook_fallback_when_not_git_repo(handler, session_id, tmp_path):
    """Test that stop hook falls back to all files when not in a git repo."""
    # Change to tmp directory
    original_cwd = Path.cwd()
    os.chdir(tmp_path)

    try:
        # Don't initialize git - just create files

        # Create a Python file with violations
        bad_file = tmp_path / "bad_code.py"
        bad_file.write_text("""
try:
    something()
except:  # Bare except
    pass
""")

        # Create node_modules (would be ignored if git was present)
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        node_file = node_modules / "package.py"
        node_file.write_text("""
try:
    x = 1
except:
    pass
""")

        # Create stop hook request
        request = StopRequest(
            hook_event_name="Stop",
            session_id=str(session_id),
        )

        # Handle the hook
        result = handler.handle("Stop", request)

        # Should find violations in all files (no git = no gitignore)
        response_dict = result.model_dump()

        # Both files have bare except violations, so we expect 4 total violations
        # (2 from AST checker, 2 from ruff)
        assert response_dict == {
            "continue_": True,
            "stopReason": None,
            "suppressOutput": None,
            "decision": "block",
            "reason": f"Code has 4 errors that must be fixed:\n{bad_file}:  Line 4: Bare except clause is not allowed. Use specific exception types. [bare_except]  Line 4: Do not use bare `except` [ruff:E722]\n{node_file}:  Line 4: Bare except clause is not allowed. Use specific exception types. [bare_except]  Line 4: Do not use bare `except` [ruff:E722]\n\nCommand to check all violations:  cl2 check {bad_file} {node_file}",
        }

    finally:
        os.chdir(original_cwd)
