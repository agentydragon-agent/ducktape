"""Tests for session_start.py HookInput parsing."""

import pytest
import pytest_bazel

from tools.claude_hooks.session_start import HookInput


def test_hook_input_without_permission_mode() -> None:
    """Validate HookInput accepts missing permission_mode.

    Claude Code Web was observed (2025-01-18) not sending permission_mode
    for SessionStart:resume events, despite documentation claiming it's required.
    """
    data = {
        "session_id": "test-session",
        "cwd": "/tmp",
        "transcript_path": "/tmp/transcript.json",
        "hook_event_name": "SessionStart",
        "source": "resume",
        # Note: permission_mode intentionally omitted
    }
    result = HookInput.model_validate(data)
    assert result.permission_mode == "default"


def test_hook_input_with_permission_mode() -> None:
    """Validate HookInput accepts explicit permission_mode."""
    data = {
        "session_id": "test-session",
        "cwd": "/tmp",
        "transcript_path": "/tmp/transcript.json",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "permission_mode": "plan",
    }
    result = HookInput.model_validate(data)
    assert result.permission_mode == "plan"


@pytest.mark.parametrize("permission_mode", ["default", "plan", "acceptEdits", "dontAsk", "bypassPermissions"])
def test_hook_input_all_permission_modes(permission_mode: str) -> None:
    """Validate HookInput accepts all documented permission_mode values."""
    data = {
        "session_id": "test-session",
        "cwd": "/tmp",
        "transcript_path": "/tmp/transcript.json",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "permission_mode": permission_mode,
    }
    result = HookInput.model_validate(data)
    assert result.permission_mode == permission_mode


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact"])
def test_hook_input_all_sources(source: str) -> None:
    """Validate HookInput accepts all documented source values."""
    data = {
        "session_id": "test-session",
        "cwd": "/tmp",
        "transcript_path": "/tmp/transcript.json",
        "hook_event_name": "SessionStart",
        "source": source,
    }
    result = HookInput.model_validate(data)
    assert result.source == source


if __name__ == "__main__":
    pytest_bazel.main()
