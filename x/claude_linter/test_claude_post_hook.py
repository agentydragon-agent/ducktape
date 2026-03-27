"""Unit tests for Claude Code post-tool-use hook."""

import json
from pathlib import Path
from typing import Any

import pytest_bazel
from click.testing import CliRunner

from x.claude_linter.cli import cli


def run_post_hook(test_input: dict[str, Any]):
    """Invoke post-hook CLI in-process and return the result."""
    runner = CliRunner()
    # Unified hook command - add hook_event_name to payload
    test_input["hook_event_name"] = "PostToolUse"
    test_input.setdefault("session_id", "12345678-1234-5678-1234-567812345678")
    payload = json.dumps(test_input)
    return runner.invoke(cli, ["hook"], input=payload)


def create_write_response(file_path: str | Path, content: str) -> dict[str, Any]:
    """Create a standard Write tool input/response structure for post-hook."""
    path = Path(file_path)
    path.write_text(content)
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": str(path), "content": content},
        "tool_response": {"type": "create", "filePath": str(path)},
    }


class TestPostHook:
    """Test cases for the post-hook."""

    def test_handles_clean_files(self, tmp_path):
        """Test that post-hook handles files without violations."""
        content = """def add(a: int, b: int) -> int:
    return a + b
"""
        test_file = tmp_path / "test.py"
        test_file.write_text(content)

        result = run_post_hook(create_write_response(test_file, content))

        assert result.exit_code == 0
        assert '"continue":true' in result.output

    def test_ignores_non_python(self, tmp_path):
        """Test that post-hook ignores non-Python files."""
        test_input = create_write_response(tmp_path / "test.txt", "Not Python")
        result = run_post_hook(test_input)
        assert result.exit_code == 0

    def test_ignores_other_tools(self):
        """Test that post-hook ignores non-file-editing tools."""
        test_input = {"tool_name": "Read", "tool_input": {"file_path": "/some/file.py"}}
        result = run_post_hook(test_input)
        assert result.exit_code == 0

    def test_returns_continue(self, tmp_path):
        """Test that post-hook returns continue response (no-op without pre-commit runner)."""
        content = "x = 1\n"
        test_file = tmp_path / "test.py"
        test_file.write_text(content)

        result = run_post_hook(create_write_response(test_file, content))
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output.get("continue") is True


if __name__ == "__main__":
    pytest_bazel.main()
