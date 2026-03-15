"""Tests for post_tool_use hook."""

from pathlib import Path

import pytest
import pytest_bazel

from devinfra.claude.claude_api.hooks.post_tool_use import (
    PostToolUseHookSpecificOutput,
    PostToolUseInput,
    PostToolUseOutput,
)
from devinfra.claude.post_tool_use import _find_git_root, evaluate

_COMMON = {
    "session_id": "test-session",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/tmp",
    "permission_mode": "default",
    "hook_event_name": "PostToolUse",
    "tool_use_id": "toolu_test123",
    "tool_response": "",
}


def test_non_file_tool_returns_default(hook_settings) -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "echo hi"})
    result = evaluate(inp, hook_settings)
    assert result.hook_specific_output is None


def test_missing_file_path_returns_default(hook_settings) -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={})
    result = evaluate(inp, hook_settings)
    assert result.hook_specific_output is None


def test_nonexistent_file_returns_default(hook_settings) -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Edit", tool_input={"file_path": "/nonexistent/file.py"})
    result = evaluate(inp, hook_settings)
    assert result.hook_specific_output is None


def test_find_git_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "a" / "b"
    subdir.mkdir(parents=True)
    assert _find_git_root(subdir / "file.py") == tmp_path


def test_find_git_root_no_git(tmp_path: Path) -> None:
    assert _find_git_root(tmp_path / "file.py") is None


def test_output_serializes_camel_case() -> None:
    out = PostToolUseOutput(hook_specific_output=PostToolUseHookSpecificOutput(additional_context="formatted"))
    j = out.model_dump_json(by_alias=True)
    assert '"hookSpecificOutput"' in j
    assert '"additionalContext"' in j
    assert "formatted" in j


def test_stop_reason_requires_continue_false() -> None:
    with pytest.raises(ValueError, match="stop_reason requires continue=false"):
        PostToolUseOutput(stop_reason="done", continue_=True)


def test_stop_reason_with_continue_false() -> None:
    out = PostToolUseOutput(stop_reason="done", continue_=False)
    assert out.stop_reason == "done"
    assert out.continue_ is False


if __name__ == "__main__":
    pytest_bazel.main()
