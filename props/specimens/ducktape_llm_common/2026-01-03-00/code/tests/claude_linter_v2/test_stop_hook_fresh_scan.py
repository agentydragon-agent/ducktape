"""Test the stop hook fresh scanning functionality."""

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


def test_stop_hook_fresh_scan_finds_errors(handler, session_id, tmp_path, monkeypatch):
    """Test that stop hook runs fresh scans and finds errors."""
    # Change to tmp directory so we only scan test files using pytest's monkeypatch
    monkeypatch.chdir(tmp_path)

    # Create a Python file with violations
    bad_file = tmp_path / "bad_code.py"
    bad_file.write_text("""
try:
    something()
except:  # Bare except
    pass

def check_attr(obj):
    if hasattr(obj, 'foo'):  # hasattr usage
        return getattr(obj, 'foo')  # getattr usage
""")

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should block due to errors
    response_dict = result.model_dump()

    # Check response keys and snippets using PyHamcrest (avoid exact long-line match)
    assert_that(
        response_dict,
        has_entries(
            continue_=True,
            stopReason=None,
            suppressOutput=None,
            decision="block",
            reason=all_of(contains_string("Do not use bare `except`"), contains_string(str(bad_file))),
        ),
    )


def test_stop_hook_fresh_scan_passes_clean_code(handler, session_id, tmp_path, monkeypatch):
    """Test that stop hook passes when code is clean."""
    # Change to tmp directory so we only scan test files using pytest's monkeypatch
    monkeypatch.chdir(tmp_path)

    # Create a clean Python file
    good_file = tmp_path / "good_code.py"
    good_file.write_text("""
def add(a: int, b: int) -> int:
    return a + b

def safe_divide(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return a / b
""")

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should pass - check exact response
    response_dict = result.model_dump()
    assert response_dict == {
        "continue_": True,
        "stopReason": None,
        "suppressOutput": None,
        "decision": None,
        "reason": None,
    }


def test_stop_hook_ignores_non_python_files(handler, session_id, tmp_path, monkeypatch):
    """Test that stop hook ignores non-Python files."""
    # Change to tmp directory using pytest's monkeypatch
    monkeypatch.chdir(tmp_path)

    # Create non-Python files
    (tmp_path / "data.json").write_text('{"bad": "except"}')
    (tmp_path / "script.sh").write_text("except: something")
    (tmp_path / "README.md").write_text("# except hasattr")

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should pass (no Python files) - check exact response
    response_dict = result.model_dump()
    assert response_dict == {
        "continue_": True,
        "stopReason": None,
        "suppressOutput": None,
        "decision": None,
        "reason": None,
    }


def test_stop_hook_quality_gate_disabled(handler, session_id, tmp_path, monkeypatch):
    """Test that stop hook passes when quality gate is disabled."""
    # Disable quality gate
    handler.config_loader.config.hooks["stop"].quality_gate = False

    # Change to tmp directory using pytest's monkeypatch
    monkeypatch.chdir(tmp_path)

    # Create a Python file with violations
    bad_file = tmp_path / "bad_code.py"
    bad_file.write_text("except: pass")  # Invalid syntax but we don't care

    # Create stop hook request
    request = StopRequest(hook_event_name="Stop", session_id=str(session_id))

    # Handle the hook
    result = handler.handle("Stop", request)

    # Should pass despite errors - check exact response
    response_dict = result.model_dump()
    assert response_dict == {
        "continue_": True,
        "stopReason": None,
        "suppressOutput": None,
        "decision": None,
        "reason": None,
    }
