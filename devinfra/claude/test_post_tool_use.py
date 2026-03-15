"""Tests for post_tool_use hook."""

from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_bazel

from devinfra.claude.claude_api.hooks.post_tool_use import (
    PostToolUseHookSpecificOutput,
    PostToolUseInput,
    PostToolUseOutput,
)
from devinfra.claude.post_tool_use import _find_git_root, _format_check_result, _make_short_diff, evaluate
from devinfra.claude.precommit_runner import HookResult, RunResult

_COMMON = {
    "session_id": "test-session",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/tmp",
    "permission_mode": "default",
    "hook_event_name": "PostToolUse",
    "tool_use_id": "toolu_test123",
    "tool_response": "",
}


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


# === Diff generation tests ===


def test_make_short_diff_no_change() -> None:
    content = b"hello\nworld\n"
    assert _make_short_diff(content, content, "test.py") == ""


def test_make_short_diff_with_change() -> None:
    original = b"hello\nworld\n"
    modified = b"hello\nearth\n"
    diff = _make_short_diff(original, modified, "test.py")
    assert "a/test.py" in diff
    assert "-world" in diff
    assert "+earth" in diff


def test_make_short_diff_truncates() -> None:
    """Long diffs are truncated to _MAX_DIFF_LINES."""
    original = "".join(f"line{i}\n" for i in range(50)).encode()
    modified = "".join(f"changed{i}\n" for i in range(50)).encode()
    diff = _make_short_diff(original, modified, "big.py")
    assert "truncated" in diff


# === Format output tests ===


def test_format_check_result_basic() -> None:
    result = RunResult(
        hooks=[
            HookResult(hook_id="ruff", hook_name="ruff-format", passed=False, output="bad indent", files_modified=True)
        ],
        original_content=b"x=1\n",
        modified_content=b"x = 1\n",
    )
    output = _format_check_result(result, Path("test.py"))
    assert "1 hook failed on test.py:" in output
    assert "ruff-format (modified file)" in output
    assert "bad indent" in output
    assert "pre-commit run" in output


def test_format_check_result_with_diff() -> None:
    result = RunResult(
        hooks=[
            HookResult(hook_id="ruff", hook_name="ruff-format", passed=False, output="err1", files_modified=True),
            HookResult(hook_id="mypy", hook_name="mypy", passed=False, output="err2", files_modified=False),
        ],
        original_content=b"old\n",
        modified_content=b"new\n",
    )
    output = _format_check_result(result, Path("f.py"))
    assert "2 hooks failed" in output
    assert "Changes pre-commit would make:" in output
    assert "+new" in output


def test_format_check_result_non_zero_exit() -> None:
    result = RunResult(
        hooks=[HookResult(hook_id="mypy", hook_name="mypy", passed=False, output="type error", files_modified=False)],
        original_content=b"x = 1\n",
        modified_content=b"x = 1\n",
    )
    output = _format_check_result(result, Path("test.py"))
    assert "mypy (non-zero exit)" in output
    assert "Changes pre-commit would make:" not in output


# === Pre-commit integration tests ===


def test_precommit_with_diff(tmp_path: Path) -> None:
    """When pre-commit modifies a file, the diff is included."""
    (tmp_path / ".git").mkdir()
    test_file = tmp_path / "test.py"
    test_file.write_bytes(b"x=1\n")

    fake_result = RunResult(
        hooks=[
            HookResult(
                hook_id="ruff-format",
                hook_name="ruff-format",
                passed=False,
                output="- files were modified by this hook",
                files_modified=True,
            )
        ],
        original_content=b"x=1\n",
        modified_content=b"x = 1\n",
    )

    with patch("devinfra.claude.post_tool_use.run_on_file", return_value=fake_result):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is not None
    ctx = result.hook_specific_output.additional_context
    assert ctx is not None
    assert "-x=1" in ctx
    assert "+x = 1" in ctx


def test_precommit_no_file_change(tmp_path: Path) -> None:
    """When pre-commit fails but doesn't modify the file, no diff is shown."""
    (tmp_path / ".git").mkdir()
    test_file = tmp_path / "test.yaml"
    test_file.write_bytes(b"key: value\n")

    fake_result = RunResult(
        hooks=[
            HookResult(
                hook_id="check-yaml", hook_name="check-yaml", passed=False, output="invalid yaml", files_modified=False
            )
        ],
        original_content=b"key: value\n",
        modified_content=b"key: value\n",
    )

    with patch("devinfra.claude.post_tool_use.run_on_file", return_value=fake_result):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is not None
    ctx = result.hook_specific_output.additional_context
    assert ctx is not None
    assert "Changes pre-commit would make:" not in ctx


def test_precommit_passes(tmp_path: Path) -> None:
    """When all hooks pass, no output is returned."""
    (tmp_path / ".git").mkdir()
    test_file = tmp_path / "clean.py"
    test_file.write_bytes(b"x = 1\n")

    fake_result = RunResult(
        hooks=[
            HookResult(hook_id="ruff-format", hook_name="ruff-format", passed=True, output="", files_modified=False)
        ],
        original_content=b"x = 1\n",
        modified_content=b"x = 1\n",
    )

    with patch("devinfra.claude.post_tool_use.run_on_file", return_value=fake_result):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is None


def test_precommit_error_returns_default(tmp_path: Path) -> None:
    """When run_on_file raises an exception, no output is returned."""
    (tmp_path / ".git").mkdir()
    test_file = tmp_path / "slow.py"
    test_file.write_bytes(b"x = 1\n")

    with patch("devinfra.claude.post_tool_use.run_on_file", side_effect=OSError("something broke")):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is None


def test_no_config_file(tmp_path: Path) -> None:
    """When no config exists (empty RunResult), no output is returned."""
    (tmp_path / ".git").mkdir()
    test_file = tmp_path / "file.py"
    test_file.write_bytes(b"x = 1\n")

    with patch("devinfra.claude.post_tool_use.run_on_file", return_value=RunResult()):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is None


def test_precommit_multiple_hooks_fail(tmp_path: Path) -> None:
    """Multiple hooks failing reports correct count."""
    (tmp_path / ".git").mkdir()
    test_file = tmp_path / "test.py"
    test_file.write_bytes(b"x=1\n")

    fake_result = RunResult(
        hooks=[
            HookResult(
                hook_id="ruff-format",
                hook_name="ruff-format",
                passed=False,
                output="- files were modified",
                files_modified=True,
            ),
            HookResult(
                hook_id="ruff-check",
                hook_name="ruff-check",
                passed=False,
                output="E001 bad style",
                files_modified=False,
            ),
        ],
        original_content=b"x=1\n",
        modified_content=b"x=1\n",
    )

    with patch("devinfra.claude.post_tool_use.run_on_file", return_value=fake_result):
        inp = PostToolUseInput(**_COMMON, tool_name="Write", tool_input={"file_path": str(test_file)})
        result = evaluate(inp)

    assert result.hook_specific_output is not None
    ctx = result.hook_specific_output.additional_context
    assert ctx is not None
    assert "2 hooks failed" in ctx


if __name__ == "__main__":
    pytest_bazel.main()
