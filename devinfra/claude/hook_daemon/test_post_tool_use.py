"""Tests for post_tool_use hook."""

from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_bazel
from syrupy.assertion import SnapshotAssertion

from devinfra.claude.claude_api.hooks.post_tool_use import (
    PostToolUseHookSpecificOutput,
    PostToolUseInput,
    PostToolUseOutput,
)
from devinfra.claude.hook_daemon.post_tool_use import _find_git_root, _format_check_result, evaluate
from devinfra.claude.hook_daemon.precommit_runner import HookResult, RunResult

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
    """Create a tmp git project with a test file, return (project_dir, test_file)."""
    (tmp_path / ".git").mkdir()
    test_file = tmp_path / "test.py"
    test_file.write_bytes(b"x=1\n")
    return tmp_path, test_file


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


# === Git root tests ===


def test_find_git_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "a" / "b"
    subdir.mkdir(parents=True)
    assert _find_git_root(subdir / "file.py") == tmp_path


def test_find_git_root_no_git(tmp_path: Path) -> None:
    assert _find_git_root(tmp_path / "file.py") is None


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
    result = RunResult(
        hooks=[
            HookResult(hook_id="ruff", hook_name="ruff-format", output=b"bad indent", files_modified=True, exit_code=1)
        ]
    )
    assert _format_check_result(result, Path("test.py")) == snapshot


def test_format_non_zero_exit(snapshot: SnapshotAssertion) -> None:
    result = RunResult(
        hooks=[HookResult(hook_id="mypy", hook_name="mypy", output=b"type error", files_modified=False, exit_code=1)]
    )
    assert _format_check_result(result, Path("test.py")) == snapshot


def test_format_auto_applied_only(snapshot: SnapshotAssertion) -> None:
    result = RunResult(
        hooks=[
            HookResult(
                hook_id="ruff-format",
                hook_name="ruff-format",
                output=b"1 file reformatted",
                files_modified=True,
                exit_code=0,
                auto_applied=True,
            )
        ]
    )
    assert _format_check_result(result, Path("test.py")) == snapshot


def test_format_mixed_auto_apply_and_report(snapshot: SnapshotAssertion) -> None:
    result = RunResult(
        hooks=[
            HookResult(
                hook_id="ruff-format",
                hook_name="ruff-format",
                output=b"reformatted",
                files_modified=True,
                exit_code=0,
                auto_applied=True,
            ),
            HookResult(
                hook_id="ruff-check",
                hook_name="ruff-check",
                output=b"F401 unused import",
                files_modified=False,
                exit_code=1,
            ),
        ]
    )
    assert _format_check_result(result, Path("test.py")) == snapshot


def test_format_with_diff(snapshot: SnapshotAssertion) -> None:
    result = RunResult(
        hooks=[HookResult(hook_id="fixer", hook_name="fixer", output=b"fixed", files_modified=True, exit_code=1)],
        report_only_diff=["@@ -1 +1 @@\n", "-x=1\n", "+x = 1\n"],
    )
    assert _format_check_result(result, Path("test.py")) == snapshot


# === RunResult property tests ===


def test_run_result_all_passed_with_auto_applied() -> None:
    result = RunResult(
        hooks=[
            HookResult(
                hook_id="ruff-format",
                hook_name="ruff-format",
                output=b"",
                files_modified=True,
                exit_code=0,
                auto_applied=True,
            ),
            HookResult(hook_id="check-ast", hook_name="check-ast", output=b"", files_modified=False, exit_code=0),
        ]
    )
    assert result.all_passed


def test_run_result_failed_hooks_excludes_auto_applied() -> None:
    result = RunResult(
        hooks=[
            HookResult(
                hook_id="ruff-format",
                hook_name="ruff-format",
                output=b"",
                files_modified=True,
                exit_code=0,
                auto_applied=True,
            ),
            HookResult(hook_id="ruff-check", hook_name="ruff-check", output=b"err", files_modified=False, exit_code=1),
        ]
    )
    assert len(result.failed_hooks) == 1
    assert result.failed_hooks[0].hook_id == "ruff-check"


# === Integration tests (mocked run_on_file) ===


def test_precommit_report_only_failure(git_project: tuple[Path, Path]) -> None:
    _, test_file = git_project

    fake_result = RunResult(
        hooks=[
            HookResult(
                hook_id="ruff-format",
                hook_name="ruff-format",
                output=b"- files were modified by this hook",
                files_modified=True,
                exit_code=0,
            )
        ]
    )

    with patch("devinfra.claude.hook_daemon.post_tool_use.run_on_file", return_value=fake_result):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is not None
    ctx = result.hook_specific_output.additional_context
    assert ctx is not None
    assert "ruff-format (modified file)" in ctx


def test_precommit_passes(git_project: tuple[Path, Path]) -> None:
    _, test_file = git_project

    fake_result = RunResult(
        hooks=[
            HookResult(hook_id="ruff-format", hook_name="ruff-format", output=b"", files_modified=False, exit_code=0)
        ]
    )

    with patch("devinfra.claude.hook_daemon.post_tool_use.run_on_file", return_value=fake_result):
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
        hooks=[
            HookResult(
                hook_id="ruff-format",
                hook_name="ruff-format",
                output=b"1 file reformatted",
                files_modified=True,
                exit_code=0,
                auto_applied=True,
            )
        ]
    )

    with patch("devinfra.claude.hook_daemon.post_tool_use.run_on_file", return_value=fake_result):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is not None
    ctx = result.hook_specific_output.additional_context
    assert ctx is not None
    assert "Auto-applied: ruff-format" in ctx


if __name__ == "__main__":
    pytest_bazel.main()
