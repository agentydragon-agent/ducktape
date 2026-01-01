"""Test the stop hook quality gate functionality."""

import pytest

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


def test_stop_hook_blocks_with_unfixed_errors(handler, session_id, tmp_path):
    """Test that stop hook blocks when there are unfixed errors."""
    # Add some violations to the tracker
    handler.violation_tracker.add_violation(
        session_id=session_id,
        file_path="/test/file.py",
        line=10,
        message="Bare except clause not allowed",
        severity="error",
        rule="bare-except",
    )
    handler.violation_tracker.add_violation(
        session_id=session_id,
        file_path="/test/file.py",
        line=20,
        message="Using hasattr() is not allowed",
        severity="error",
        rule="no-hasattr",
    )
    handler.violation_tracker.add_violation(
        session_id=session_id,
        file_path="/test/other.py",
        line=5,
        message="Line too long",
        severity="warning",
        rule="E501",
    )

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should block due to errors
    response_dict = result.model_dump()
    assert response_dict.get("continue_") is True  # Always True for hook responses
    assert response_dict.get("decision") == "block"  # StopPrevent sets decision=block
    assert response_dict.get("reason") is not None
    reason = response_dict["reason"]
    assert "2 errors that must be fixed" in reason
    assert "/test/file.py" in reason
    assert "/test/other.py" in reason
    assert "Line 10:" in reason or "Line 20:" in reason  # Should show line numbers
    assert "cl2 check" in reason  # Should include check command


def test_stop_hook_allows_with_only_warnings(handler, session_id, tmp_path):
    """Test that stop hook allows proceeding with only warnings."""
    # Add only warnings
    handler.violation_tracker.add_violation(
        session_id=session_id,
        file_path="/test/file.py",
        line=10,
        message="Line too long",
        severity="warning",
        rule="E501",
    )
    handler.violation_tracker.add_violation(
        session_id=session_id,
        file_path="/test/file.py",
        line=20,
        message="Missing docstring",
        severity="warning",
        rule="D100",
    )

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should allow stop (only warnings)
    response_dict = result.model_dump()
    assert response_dict.get("continue_") is True  # StopAllow has continue_=True
    assert response_dict.get("decision") is None  # StopAllow doesn't set decision


def test_stop_hook_passes_with_no_violations(handler, session_id, tmp_path):
    """Test that stop hook passes when there are no violations."""
    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should pass
    response_dict = result.model_dump()
    assert response_dict.get("continue_") is True  # StopAllow has continue_=True
    assert response_dict.get("decision") is None  # StopAllow doesn't set decision


def test_stop_hook_passes_when_quality_gate_disabled(handler, session_id, tmp_path):
    """Test that stop hook passes when quality gate is disabled."""
    # Disable quality gate
    handler.config_loader.config.hooks["stop"].quality_gate = False

    # Add violations
    handler.violation_tracker.add_violation(
        session_id=session_id,
        file_path="/test/file.py",
        line=10,
        message="Bare except clause not allowed",
        severity="error",
    )

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should pass despite errors
    response_dict = result.model_dump()
    assert response_dict.get("continue_") is True  # StopAllow has continue_=True
    assert response_dict.get("decision") is None  # StopAllow doesn't set decision


def test_violations_marked_as_fixed(handler, session_id, tmp_path):
    """Test that violations can be marked as fixed."""
    # Add violations
    handler.violation_tracker.add_violation(
        session_id=session_id, file_path="/test/file.py", line=10, message="Bare except clause", severity="error"
    )
    handler.violation_tracker.add_violation(
        session_id=session_id, file_path="/test/file.py", line=20, message="Line too long", severity="warning"
    )
    handler.violation_tracker.add_violation(
        session_id=session_id, file_path="/test/other.py", line=5, message="Missing docstring", severity="warning"
    )

    # Mark one file as fixed
    handler.violation_tracker.mark_file_fixed(session_id, "/test/file.py")

    # Check unfixed violations
    unfixed = handler.violation_tracker.get_unfixed_violations(session_id)
    assert len(unfixed) == 1
    assert unfixed[0].file_path == "/test/other.py"

    # Stop hook should only report the unfixed violation
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    result = handler.handle("Stop", request)
    # Since only warnings remain, should allow stop
    response_dict = result.model_dump()
    assert response_dict.get("continue_") is True  # Only warnings - allows stop
    assert response_dict.get("decision") is None  # StopAllow doesn't set decision


def test_violation_deduplication(handler, session_id):
    """Test that duplicate violations are deduplicated."""
    # Add same violation multiple times
    for _ in range(3):
        handler.violation_tracker.add_violation(
            session_id=session_id,
            file_path="/test/file.py",
            line=10,
            message="Bare except clause not allowed",
            severity="error",
            rule="bare-except",
        )

    # Should only have one violation
    unfixed = handler.violation_tracker.get_unfixed_violations(session_id)
    assert len(unfixed) == 1
