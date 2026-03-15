"""Tests for pre_tool_use hook."""

from __future__ import annotations

import pytest_bazel

from devinfra.claude.claude_api.pre_tool_use import PermissionDecision, PreToolUseInput
from devinfra.claude.pre_tool_use import evaluate

_COMMON = {
    "session_id": "test-session",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/tmp",
    "permission_mode": "default",
    "hook_event_name": "PreToolUse",
    "tool_use_id": "toolu_test123",
}


class TestEvaluate:
    def test_allowed_bash_command_returns_allow(self) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "echo hello world"})
        result = evaluate(hook_input)
        assert result is not None
        assert result.hook_specific_output.permission_decision == PermissionDecision.ALLOW

    def test_output_serializes_to_camel_case(self) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "echo hello world"})
        result = evaluate(hook_input)
        assert result is not None
        json_output = result.model_dump_json(by_alias=True)
        assert "hookSpecificOutput" in json_output
        assert "permissionDecision" in json_output
        assert "hook_specific_output" not in json_output

    def test_unknown_bash_command_returns_none(self) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "rm -rf /"})
        assert evaluate(hook_input) is None

    def test_non_bash_tool_returns_none(self) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Read", tool_input={"file_path": "/etc/passwd"})
        assert evaluate(hook_input) is None

    def test_bash_without_command_key_returns_none(self) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={})
        assert evaluate(hook_input) is None


if __name__ == "__main__":
    pytest_bazel.main()
