"""Unit tests for SessionStartHookInput parsing."""

import pytest
import pytest_bazel

from devinfra.claude.claude_api.hook_input import PermissionMode, SessionStartHookInput

_SESSION_START_JSON = {
    "session_id": "test-session",
    "cwd": "/tmp",
    "transcript_path": "/tmp/transcript.json",
    "hook_event_name": "SessionStart",
    "source": "startup",
}


def test_missing_permission_mode_defaults_to_none() -> None:
    """Claude Code Web was observed (2025-01-18) not sending permission_mode
    for SessionStart:resume events, despite documentation claiming it's required.
    """
    data = {**_SESSION_START_JSON, "source": "resume"}
    result = SessionStartHookInput.model_validate(data)
    assert result.permission_mode is None


def test_explicit_permission_mode() -> None:
    result = SessionStartHookInput.model_validate({**_SESSION_START_JSON, "permission_mode": "plan"})
    assert result.permission_mode == PermissionMode.PLAN


def test_model_field() -> None:
    result = SessionStartHookInput.model_validate({**_SESSION_START_JSON, "model": "claude-sonnet-4-20250514"})
    assert result.model == "claude-sonnet-4-20250514"


@pytest.mark.parametrize("permission_mode", list(PermissionMode))
def test_all_permission_modes(permission_mode: PermissionMode) -> None:
    result = SessionStartHookInput.model_validate({**_SESSION_START_JSON, "permission_mode": permission_mode})
    assert result.permission_mode == permission_mode


if __name__ == "__main__":
    pytest_bazel.main()
