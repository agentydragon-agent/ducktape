"""Unit tests for HookInput parsing."""

from __future__ import annotations

import pytest
import pytest_bazel

from devinfra.claude.claude_api.hook_input import HookInput, PermissionMode


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
    assert result.permission_mode == PermissionMode.DEFAULT


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
    assert result.permission_mode == PermissionMode.PLAN


def test_hook_input_with_model_field() -> None:
    """Validate HookInput accepts the model field."""
    data = {
        "session_id": "test-session",
        "cwd": "/tmp",
        "transcript_path": "/tmp/transcript.json",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "permission_mode": "default",
        "model": "claude-sonnet-4-20250514",
    }
    result = HookInput.model_validate(data)
    assert result.model == "claude-sonnet-4-20250514"


@pytest.mark.parametrize("permission_mode", list(PermissionMode))
def test_hook_input_all_permission_modes(permission_mode: PermissionMode) -> None:
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


if __name__ == "__main__":
    pytest_bazel.main()
