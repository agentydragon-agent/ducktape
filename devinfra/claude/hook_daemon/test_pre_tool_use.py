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
    def test_allowed_bash_command_returns_allow(self, command: str, session: Session) -> None:
        hook_input = PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": command})
        result = evaluate(hook_input, session)
        assert result.hook_specific_output is not None
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
        [("Bash", {"command": "rm -rf /"}), ("Read", {"file_path": "/etc/passwd"}), ("Bash", {})],
        ids=["unknown-bash-command", "non-bash-tool", "bash-without-command"],
    )
    def test_returns_no_decision_for_unmatched(self, tool_name: str, tool_input: dict, session: Session) -> None:
        # Unmatched tools return no hook_specific_output (implicit allow — no blocking decision)
        hook_input = PreToolUseInput(**_COMMON, tool_name=tool_name, tool_input=tool_input)
        result = evaluate(hook_input, session)
        assert result.hook_specific_output is None


@pytest.fixture
def hook_input() -> PreToolUseInput:
    return PreToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "ls"})


async def test_no_message_while_task_running(session: Session, hook_input: PreToolUseInput) -> None:
    # Task still running: system_message must be None (must not block)
    async def never_complete() -> precommit.PrecommitHooksResult:
        await asyncio.sleep(1000)
        return precommit.PrecommitHooksInstalled()

    task: asyncio.Task[precommit.PrecommitHooksResult] = asyncio.create_task(never_complete())
    session.register_precommit_install(task)
    result = evaluate(hook_input, session)
    assert result.system_message is None
    task.cancel()


async def test_precommit_success_surfaced_after_task_done(session: Session, hook_input: PreToolUseInput) -> None:
    async def succeed() -> precommit.PrecommitHooksResult:
        return precommit.PrecommitHooksInstalled()

    task: asyncio.Task[precommit.PrecommitHooksResult] = asyncio.create_task(succeed())
    await asyncio.sleep(0)  # yield to let task complete
    session.register_precommit_install(task)
    result = evaluate(hook_input, session)
    assert result.system_message is not None
    assert "completed successfully" in result.system_message


async def test_precommit_failure_surfaced_after_task_done(session: Session, hook_input: PreToolUseInput) -> None:
    async def fail() -> precommit.PrecommitHooksResult:
        return precommit.PrecommitHooksFailed(error=RuntimeError("hook env error"))

    task: asyncio.Task[precommit.PrecommitHooksResult] = asyncio.create_task(fail())
    await asyncio.sleep(0)
    session.register_precommit_install(task)
    result = evaluate(hook_input, session)
    assert result.system_message is not None
    assert "failed" in result.system_message


async def test_precommit_status_consumed_only_once(session: Session, hook_input: PreToolUseInput) -> None:
    # Once consumed, subsequent calls return None
    async def succeed() -> precommit.PrecommitHooksResult:
        return precommit.PrecommitHooksInstalled()

    task: asyncio.Task[precommit.PrecommitHooksResult] = asyncio.create_task(succeed())
    await asyncio.sleep(0)
    session.register_precommit_install(task)
    first = evaluate(hook_input, session)
    second = evaluate(hook_input, session)
    assert first.system_message is not None
    assert second.system_message is None


if __name__ == "__main__":
    pytest_bazel.main()
