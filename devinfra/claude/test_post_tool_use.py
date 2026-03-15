"""Tests for post_tool_use hook."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from devinfra.claude.claude_api.hook_input import PermissionMode
from devinfra.claude.claude_api.post_tool_use import PostToolUseInput, PostToolUseOutput
from devinfra.claude.post_tool_use import _find_git_root, evaluate

_COMMON = {
    "session_id": "test-session",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/tmp",
    "permission_mode": PermissionMode.DEFAULT,
    "hook_event_name": "PostToolUse",
    "tool_use_id": "toolu_test123",
}


def test_non_file_tool_returns_none() -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "echo hi"})
    assert evaluate(inp) is None


def test_missing_file_path_returns_none() -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={})
    assert evaluate(inp) is None


def test_nonexistent_file_returns_none() -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Edit", tool_input={"file_path": "/nonexistent/file.py"})
    assert evaluate(inp) is None


def test_find_git_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "a" / "b"
    subdir.mkdir(parents=True)
    assert _find_git_root(subdir / "file.py") == tmp_path


def test_find_git_root_no_git(tmp_path: Path) -> None:
    assert _find_git_root(tmp_path / "file.py") is None


def test_output_serializes_camel_case() -> None:
    out = PostToolUseOutput(additional_context="formatted")
    j = out.model_dump_json(by_alias=True)
    assert '"additionalContext"' in j
    assert "formatted" in j


if __name__ == "__main__":
    pytest_bazel.main()
