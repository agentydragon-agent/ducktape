#!/usr/bin/env python3
"""Unit tests for Claude Code post-tool-use hook."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_post_hook(test_input: dict[str, Any]) -> subprocess.CompletedProcess:
    """Run the post-hook with given input and return the result."""
    return subprocess.run(
        [sys.executable, "-m", "ducktape_llm_common.linters.claude_post_hook"],
        input=json.dumps(test_input),
        capture_output=True,
        text=True,
    )


def create_write_response(file_path: str | Path, content: str) -> dict[str, Any]:
    """Create a standard Write tool input/response structure for post-hook."""
    file_path = str(file_path)
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
        "tool_response": {"type": "create", "filePath": file_path},
    }


class TestPostHook:
    """Test cases for the post-hook."""

    def test_fixes_violations(self, tmp_path):
        """Test that post-hook auto-fixes violations."""
        content = """from typing import Union, Optional

def process(value: Union[str, int]) -> Optional[str]:
    if value:
        return str(value)
    else:
        return None
"""
        # Create a temporary file with fixable violations
        test_file = tmp_path / "test.py"
        test_file.write_text(content)

        result = run_post_hook(create_write_response(test_file, content))

        # Should exit with code 0 (success)
        assert result.returncode == 0

        # Check that file was modified
        fixed_content = test_file.read_text()

        # Should have fixed Union to |
        assert "str | int" in fixed_content
        assert "Union[str, int]" not in fixed_content

        # Should have fixed Optional to | None
        assert "str | None" in fixed_content
        assert "Optional[str]" not in fixed_content

        # Should show what was fixed (output goes to stderr for Claude)
        assert "Auto-fixed" in result.stderr

    def test_reports_fixes(self, tmp_path):
        """Test that post-hook reports fixes to stderr for Claude to see."""
        content = """from typing import Union

def foo(x: Union[str, int]) -> str:
    return str(x)
"""
        test_file = tmp_path / "test.py"
        test_file.write_text(content)

        result = run_post_hook(create_write_response(test_file, content))

        assert result.returncode == 0
        assert "Auto-fixed" in result.stderr or "Fixed" in result.stderr

    def test_handles_clean_files(self, tmp_path):
        """Test that post-hook handles files without violations."""
        content = """def add(a: int, b: int) -> int:
    return a + b
"""
        test_file = tmp_path / "test.py"
        test_file.write_text(content)

        result = run_post_hook(create_write_response(test_file, content))

        assert result.returncode == 0
        # No fixes needed - should have no output
        assert result.stderr.strip() == "" or "No auto-fixes needed" in result.stderr

    def test_ignores_non_python(self, tmp_path):
        """Test that post-hook ignores non-Python files."""
        test_input = create_write_response(tmp_path / "test.txt", "Not Python")
        result = run_post_hook(test_input)
        assert result.returncode == 0

    def test_handles_edit_tool(self, tmp_path):
        """Test that post-hook handles Edit tool."""
        content = """from typing import Union

def foo(x: Union[str, int]) -> str:
    return str(x)
"""
        test_file = tmp_path / "test.py"
        test_file.write_text(content)

        test_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(test_file), "old_string": "foo", "new_string": "bar"},
        }
        result = run_post_hook(test_input)

        assert result.returncode == 0
        # Check that file was auto-fixed
        fixed_content = test_file.read_text()
        assert "str | int" in fixed_content

    def test_ignores_other_tools(self):
        """Test that post-hook ignores non-file-editing tools."""
        test_input = {"tool_name": "Read", "tool_input": {"file_path": "/some/file.py"}}
        result = run_post_hook(test_input)
        assert result.returncode == 0

    def test_formats_code(self, tmp_path):
        """Test that post-hook runs ruff format."""
        # Intentionally poorly formatted code
        content = """def   foo(  x:int,y:int   )->int:
    return x+y
"""
        test_file = tmp_path / "test.py"
        test_file.write_text(content)

        result = run_post_hook(create_write_response(test_file, content))

        assert result.returncode == 0

        # Check formatting was applied
        formatted_content = test_file.read_text()

        # Should be properly formatted now
        assert "def foo(x: int, y: int) -> int:" in formatted_content
        assert "return x + y" in formatted_content
