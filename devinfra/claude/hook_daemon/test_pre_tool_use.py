"""Tests for pre_tool_use hook."""

from pathlib import Path

import pytest
import pytest_bazel

from devinfra.claude.claude_api.hooks.pre_tool_use import (
    PermissionDecision,
    PreToolUseHookSpecificOutput,
    PreToolUseInput,
)
from devinfra.claude.hook_daemon.pre_tool_use import ALWAYS_ALLOW_COMMANDS, evaluate
from devinfra.claude.hook_daemon.session import Session
from devinfra.claude.hook_daemon.testing.testing_helpers import TEST_PROFILE
from devinfra.claude.session_paths import SessionPaths


@pytest.fixture
def session() -> Session:
    return Session(
        session_id="test-session",
        paths=SessionPaths(session_id="test-session", home=Path("/tmp"), xdg_cache_home=Path("/tmp")),
        profile=TEST_PROFILE,
    )


_COMMON = {
    "session_id": "test-session",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/tmp",
    "permission_mode": "default",
    "hook_event_name": "PreToolUse",
    "tool_use_id": "toolu_test123",
}


class TestEvaluate:
    @pytest.mark.parametrize("command", sorted(ALWAYS_ALLOW_COMMANDS))
    def test_allowed_bash_command_returns_allow(self, session: Session, command: str) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": command})
        result = evaluate(hook_input, session)
        assert result.hook_specific_output is not None
        assert isinstance(result.hook_specific_output, PreToolUseHookSpecificOutput)
        assert result.hook_specific_output.permission_decision == PermissionDecision.ALLOW

    def test_output_serializes_to_camel_case(self, session: Session) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "echo hello world"})
        result = evaluate(hook_input, session)
        json_output = result.model_dump_json(by_alias=True)
        assert "hookSpecificOutput" in json_output
        assert "permissionDecision" in json_output
        assert "hook_specific_output" not in json_output

    @pytest.mark.parametrize(
        ("tool_name", "tool_input"),
        [("Bash", {"command": "rm -rf /"}), ("Read", {"file_path": "/etc/passwd"})],
        ids=["unknown-bash-command", "non-bash-tool"],
    )
    def test_returns_no_decision_for_unmatched(self, session: Session, tool_name: str, tool_input: dict) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name=tool_name, tool_input=tool_input)
        result = evaluate(hook_input, session)
        assert result.hook_specific_output is None


class TestParsingFailOpen:
    def test_malformed_bash_input_returns_no_decision(self, session: Session) -> None:
        """Missing 'command' field causes parse failure → fail-open (no decision)."""
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={})
        result = evaluate(hook_input, session)
        assert result.hook_specific_output is None

    def test_malformed_bash_input_posts_mailbox_warning(self, session: Session) -> None:
        """Parse failure posts a warning to session mailbox."""
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={})
        evaluate(hook_input, session)
        messages = session.drain_messages()
        assert len(messages) == 1
        assert "Failed to parse Bash" in messages[0]

    def test_unknown_tool_returns_no_decision(self, session: Session) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="MCPTool", tool_input={"whatever": True})
        result = evaluate(hook_input, session)
        assert result.hook_specific_output is None


# === Session mailbox tests ===


def test_post_and_drain(session: Session) -> None:
    session.post_message("hello")
    session.post_message("world")
    assert session.drain_messages() == ["hello", "world"]


def test_drain_clears(session: Session) -> None:
    session.post_message("hello")
    session.drain_messages()
    assert session.drain_messages() == []


def test_empty_drain(session: Session) -> None:
    assert session.drain_messages() == []


if __name__ == "__main__":
    pytest_bazel.main()
