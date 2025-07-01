#!/usr/bin/env python3
"""Unit tests for Claude Code pre-tool-use hook."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_pre_hook(test_input: dict[str, Any]) -> subprocess.CompletedProcess:
    """Run the pre-hook with given input and return the result."""
    return subprocess.run(
        [sys.executable, "-m", "ducktape_llm_common.linters.claude_pre_hook"],
        input=json.dumps(test_input),
        capture_output=True,
        text=True,
    )


def create_write_input(file_path: str | Path, content: str) -> dict[str, Any]:
    """Create a standard Write tool input structure."""
    return {"tool_name": "Write", "tool_input": {"file_path": str(file_path), "content": content}}


class TestPreHook:
    """Test cases for the pre-hook."""

    def test_blocks_non_fixable_violations(self, tmp_path):
        """Test that pre-hook blocks files with non-fixable violations like S113."""
        content = """import requests

def fetch_data(url):
    response = requests.get(url)  # S113 - missing timeout
    return response.text
"""
        file_path = tmp_path / "test_requests.py"
        result = run_pre_hook(create_write_input(file_path, content))

        # Should exit with code 2 (blocking error)
        assert result.returncode == 2
        assert "NON-FIXABLE VIOLATIONS DETECTED" in result.stderr
        assert "S113" in result.stderr
        assert "timeout" in result.stderr.lower()

    def test_allows_clean_files(self, tmp_path):
        """Test that pre-hook allows files without violations."""
        content = """def add(a: int, b: int) -> int:
    return a + b
"""
        file_path = tmp_path / "test_clean.py"
        result = run_pre_hook(create_write_input(file_path, content))

        assert result.returncode == 0
        assert "VIOLATIONS DETECTED" not in result.stderr

    def test_allows_auto_fixable_only(self, tmp_path):
        """Test that pre-hook allows files with only auto-fixable violations."""
        content = """from typing import Union, Optional

def process(value: Union[str, int]) -> Optional[str]:
    if value:
        return str(value)
    else:
        return None
"""
        file_path = tmp_path / "test_fixable.py"
        result = run_pre_hook(create_write_input(file_path, content))

        assert result.returncode == 0
        assert "NON-FIXABLE VIOLATIONS" not in result.stderr

    def test_ignores_non_python_files(self, tmp_path):
        """Test that pre-hook ignores non-Python files."""
        test_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / "test.txt"), "content": "This is not Python code"},
        }
        result = run_pre_hook(test_input)
        assert result.returncode == 0

    def test_ignores_other_tools(self, tmp_path):
        """Test that pre-hook ignores non-Write tools."""
        test_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(tmp_path / "test.py"), "old_string": "foo", "new_string": "bar"},
        }
        result = run_pre_hook(test_input)
        assert result.returncode == 0

    def test_handles_invalid_json(self):
        """Test that pre-hook handles invalid JSON gracefully."""
        result = subprocess.run(
            [sys.executable, "-m", "ducktape_llm_common.linters.claude_pre_hook"],
            input="not valid json",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Error parsing JSON input" in result.stderr

    def test_multiple_violations(self, tmp_path):
        """Test pre-hook with multiple non-fixable violations."""
        content = """import requests
import subprocess

def fetch(url):
    return requests.get(url).text  # S113

def run_cmd(cmd):
    subprocess.run(cmd)  # S603 - subprocess without shell safety check
"""
        file_path = tmp_path / "test_multiple.py"
        result = run_pre_hook(create_write_input(file_path, content))

        assert result.returncode == 2
        assert "S113" in result.stderr
        # Note: S603 might be auto-fixable in some cases, so we don't assert on it
