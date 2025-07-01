#!/usr/bin/env python3
"""Unit tests for the unified Claude linter binary."""

import subprocess
import sys


def run_claude_linter(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    """Run the claude-linter command with given arguments."""
    cmd = [sys.executable, "-m", "ducktape_llm_common.linters.claude_linter"] + args
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True)


class TestUnifiedLinter:
    """Test cases for the unified linter entry point."""

    def test_pre_mode(self):
        """Test that 'claude-linter pre' runs the pre-hook."""
        result = run_claude_linter(["pre"], "invalid json")

        # Pre-hook should fail with JSON decode error
        assert result.returncode == 1
        assert "Error parsing JSON input" in result.stderr

    def test_post_mode(self):
        """Test that 'claude-linter post' runs the post-hook."""
        result = run_claude_linter(["post"], "invalid json")

        # Post-hook should fail with JSON decode error
        assert result.returncode == 1
        assert "Error parsing JSON input" in result.stderr

    def test_invalid_mode(self):
        """Test that invalid mode is rejected."""
        result = run_claude_linter(["invalid"])

        # Should fail with argument error
        assert result.returncode == 2
        assert "invalid choice: 'invalid'" in result.stderr

    def test_no_mode(self):
        """Test that missing mode is rejected."""
        result = run_claude_linter([])

        # Should fail with argument error
        assert result.returncode == 2
        assert "required: mode" in result.stderr

    def test_help(self):
        """Test that help text shows both modes."""
        result = run_claude_linter(["--help"])

        assert result.returncode == 0
        assert "pre" in result.stdout
        assert "post" in result.stdout
        assert "Pre-tool-use hook" in result.stdout
        assert "Post-tool-use hook" in result.stdout
