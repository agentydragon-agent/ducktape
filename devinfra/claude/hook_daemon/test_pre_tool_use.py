"""Tests for pre_tool_use hook."""

import asyncio
from pathlib import Path

import pytest
import pytest_bazel

from devinfra.claude.claude_api.hooks.pre_tool_use import PermissionDecision, PreToolUseInput
from devinfra.claude.hook_daemon.pre_tool_use import ALWAYS_ALLOW_COMMANDS, evaluate
from devinfra.claude.hook_daemon.session import Session
from devinfra.claude.hook_daemon.session_start import precommit
from devinfra.claude.session_paths import SessionPaths


@pytest.fixture
def session() -> Session:
    return Session(
        session_id="test-session",
        paths=SessionPaths(session_id="test-session", home=Path("/tmp"), xdg_cache_home=Path("/tmp")),
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
    def test_allowed_bash_command_returns_allow(self, command: str) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": command})
        result = evaluate(hook_input)
        assert result.hook_specific_output is not None
        assert result.hook_specific_output.permission_decision == PermissionDecision.ALLOW

    def test_output_serializes_to_camel_case(self) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "echo hello world"})
        result = evaluate(hook_input)
        json_output = result.model_dump_json(by_alias=True)
        assert "hookSpecificOutput" in json_output
        assert "permissionDecision" in json_output
        assert "hook_specific_output" not in json_output

    @pytest.mark.parametrize(
        ("tool_name", "tool_input"),
        [("Bash", {"command": "rm -rf /"}), ("Read", {"file_path": "/etc/passwd"}), ("Bash", {})],
        ids=["unknown-bash-command", "non-bash-tool", "bash-without-command"],
    )
    def test_returns_no_decision_for_unmatched(self, tool_name: str, tool_input: dict) -> None:
        # Unmatched tools return no hook_specific_output (implicit allow — no blocking decision)
        hook_input = PreToolUseInput(**_COMMON, tool_name=tool_name, tool_input=tool_input)
        result = evaluate(hook_input)
        assert result.hook_specific_output is None


# === Background notification tests (session.take_precommit_status) ===


async def test_no_message_while_task_running(session: Session) -> None:
    async def never_complete() -> precommit.PrecommitHooksResult:
        await asyncio.sleep(1000)
        return precommit.PrecommitHooksInstalled()

    task: asyncio.Task[precommit.PrecommitHooksResult] = asyncio.create_task(never_complete())
    session.register_precommit_install(task)
    assert session.drain_messages() == []
    task.cancel()


async def test_precommit_success_surfaced_after_task_done(session: Session) -> None:
    async def succeed() -> precommit.PrecommitHooksResult:
        return precommit.PrecommitHooksInstalled()

    task: asyncio.Task[precommit.PrecommitHooksResult] = asyncio.create_task(succeed())
    await asyncio.sleep(0)  # let task complete
    session.register_precommit_install(task)
    await asyncio.sleep(0)  # let done callback fire
    messages = session.drain_messages()
    assert len(messages) == 1
    assert "completed successfully" in messages[0]


async def test_precommit_failure_surfaced_after_task_done(session: Session) -> None:
    async def fail() -> precommit.PrecommitHooksResult:
        return precommit.PrecommitHooksFailed(error=RuntimeError("hook env error"))

    task: asyncio.Task[precommit.PrecommitHooksResult] = asyncio.create_task(fail())
    await asyncio.sleep(0)  # let task complete
    session.register_precommit_install(task)
    await asyncio.sleep(0)  # let done callback fire
    messages = session.drain_messages()
    assert len(messages) == 1
    assert "failed" in messages[0]


async def test_mailbox_drained_only_once(session: Session) -> None:
    async def succeed() -> precommit.PrecommitHooksResult:
        return precommit.PrecommitHooksInstalled()

    task: asyncio.Task[precommit.PrecommitHooksResult] = asyncio.create_task(succeed())
    await asyncio.sleep(0)  # let task complete
    session.register_precommit_install(task)
    await asyncio.sleep(0)  # let done callback fire
    assert len(session.drain_messages()) == 1
    assert session.drain_messages() == []


if __name__ == "__main__":
    pytest_bazel.main()
