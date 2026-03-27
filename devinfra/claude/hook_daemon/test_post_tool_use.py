"""Tests for post_tool_use hook."""

from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_bazel
import yaml
from syrupy.assertion import SnapshotAssertion

from devinfra.claude.claude_api.hooks.post_tool_use import (
    PostToolUseHookSpecificOutput,
    PostToolUseInput,
    PostToolUseOutput,
)
from devinfra.claude.hook_config import HookConfig, PreCommitConfig
from devinfra.claude.hook_daemon.conftest import init_git_repo
from devinfra.claude.hook_daemon.post_tool_use import _format_check_result, evaluate
from devinfra.claude.hook_daemon.precommit_runner import HookAutoApplied, HookFailedNotApplied, HookWouldEdit, RunResult

_COMMON = {
    "session_id": "test-session",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/tmp",
    "permission_mode": "default",
    "hook_event_name": "PostToolUse",
    "tool_use_id": "toolu_test123",
    "tool_response": "",
}


@pytest.fixture
def git_project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a tmp git project with .claude_hooks config and a test file."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    config = HookConfig(pre_commit=PreCommitConfig())
    hooks_dir = repo_path / ".claude_hooks"
    hooks_dir.mkdir()
    (hooks_dir / "config.yaml").write_text(yaml.dump(config.model_dump(mode="json", exclude_none=True)))
    test_file = repo_path / "test.py"
    test_file.write_bytes(b"x=1\n")
    init_git_repo(repo_path)
    return repo_path, test_file


# === Guard tests ===


def test_non_file_tool_returns_default() -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Bash", tool_input={"command": "echo hi"})
    result = evaluate(inp)
    assert result.hook_specific_output is None


def test_missing_file_path_returns_default() -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={})
    result = evaluate(inp)
    assert result.hook_specific_output is None


def test_nonexistent_file_returns_default() -> None:
    inp = PostToolUseInput(**_COMMON, tool_name="Edit", tool_input={"file_path": "/nonexistent/file.py"})
    result = evaluate(inp)
    assert result.hook_specific_output is None


# === Serialization tests ===


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


# === Format output tests (snapshot) ===


def test_format_report_only_failure(snapshot: SnapshotAssertion) -> None:
    result = RunResult(hooks={"ruff": HookWouldEdit(output=b"bad indent", exit_code=1)})
    assert _format_check_result(result, Path("test.py"), PreCommitConfig()) == snapshot


def test_format_non_zero_exit(snapshot: SnapshotAssertion) -> None:
    result = RunResult(hooks={"mypy": HookFailedNotApplied(output=b"type error", exit_code=1)})
    assert _format_check_result(result, Path("test.py"), PreCommitConfig()) == snapshot


def test_format_auto_applied_only(snapshot: SnapshotAssertion) -> None:
    result = RunResult(
        hooks={"ruff-format": HookAutoApplied(output=b"1 file reformatted", exit_code=0, rerun_exit_code=0)}
    )
    assert _format_check_result(result, Path("test.py"), PreCommitConfig()) == snapshot


def test_format_mixed_auto_apply_and_report(snapshot: SnapshotAssertion) -> None:
    result = RunResult(
        hooks={
            "ruff-format": HookAutoApplied(output=b"reformatted", exit_code=0, rerun_exit_code=0),
            "ruff-check": HookFailedNotApplied(output=b"F401 unused import", exit_code=1),
        }
    )
    assert _format_check_result(result, Path("test.py"), PreCommitConfig()) == snapshot


def test_format_with_diff(snapshot: SnapshotAssertion) -> None:
    result = RunResult(
        hooks={"fixer": HookWouldEdit(output=b"fixed", exit_code=1)},
        report_only_diff=["@@ -1 +1 @@\n", "-x=1\n", "+x = 1\n"],
    )
    assert _format_check_result(result, Path("test.py"), PreCommitConfig(show_report_diffs=True)) == snapshot


# === RunResult property tests ===


def test_run_result_has_issues_false_when_all_passed() -> None:
    result = RunResult(hooks={})
    assert not result.has_issues


def test_run_result_has_issues_with_auto_applied() -> None:
    result = RunResult(hooks={"ruff-format": HookAutoApplied(output=b"", exit_code=0, rerun_exit_code=0)})
    assert result.has_issues


def test_run_result_failed_not_applied_excludes_auto_applied() -> None:
    result = RunResult(
        hooks={
            "ruff-format": HookAutoApplied(output=b"", exit_code=0, rerun_exit_code=0),
            "ruff-check": HookFailedNotApplied(output=b"err", exit_code=1),
        }
    )
    assert len(result.failed_not_applied) == 1
    assert "ruff-check" in result.failed_not_applied


# === Integration tests (mocked run_on_file) ===


def test_precommit_report_only_failure(git_project: tuple[Path, Path]) -> None:
    _, test_file = git_project

    fake_result = RunResult(hooks={"ruff-format": HookWouldEdit(output=b"modified", exit_code=0)})

    with patch("devinfra.claude.hook_daemon.post_tool_use.run_on_file", return_value=fake_result):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is not None
    ctx = result.hook_specific_output.additional_context
    assert ctx is not None
    assert "Not auto-applied" in ctx
    assert "ruff-format" in ctx


def test_precommit_passes(git_project: tuple[Path, Path]) -> None:
    _, test_file = git_project

    with patch("devinfra.claude.hook_daemon.post_tool_use.run_on_file", return_value=RunResult()):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is None


def test_no_hooks_applied(git_project: tuple[Path, Path]) -> None:
    _, test_file = git_project

    with patch("devinfra.claude.hook_daemon.post_tool_use.run_on_file", return_value=RunResult()):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is None


def test_auto_applied_only_returns_context(git_project: tuple[Path, Path]) -> None:
    _, test_file = git_project

    fake_result = RunResult(
        hooks={"ruff-format": HookAutoApplied(output=b"1 file reformatted", exit_code=0, rerun_exit_code=0)}
    )

    with patch("devinfra.claude.hook_daemon.post_tool_use.run_on_file", return_value=fake_result):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is not None
    ctx = result.hook_specific_output.additional_context
    assert ctx is not None
    assert "Auto-applied:" in ctx
    assert "ruff-format" in ctx


if __name__ == "__main__":
    pytest_bazel.main()
