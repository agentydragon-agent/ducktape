#!/usr/bin/env python3
"""Unit tests for the unified Claude linter binary."""

from click.testing import CliRunner

from ducktape_llm_common.claude_linter.cli import cli


def run_claude_linter(args: list[str], input_text: str | None = None):
    """Invoke the claude-linter CLI in-process and capture result."""
    runner = CliRunner()
    return runner.invoke(cli, args, input=input_text)


class TestUnifiedLinter:
    """Test cases for the unified linter entry point."""

    def test_pre_mode(self):
        """Test that 'claude-linter pre' runs the pre-hook."""
        result = run_claude_linter(["pre"], "invalid json")

        # Pre-hook should fail with JSON decode error
        assert result.exit_code == 1
        assert "Error parsing JSON input" in result.output

    def test_post_mode(self):
        """Test that 'claude-linter post' runs the post-hook."""
        result = run_claude_linter(["post"], "invalid json")

        # Post-hook should fail with JSON decode error
        assert result.exit_code == 1
        assert "Error parsing JSON input" in result.output

    def test_invalid_mode(self):
        """Test that invalid mode is rejected."""
        result = run_claude_linter(["invalid"])

        # Should fail with argument error
        assert result.exit_code == 2
        assert "No such command 'invalid'" in result.output

    def test_no_mode(self):
        """Test that missing mode is rejected."""
        result = run_claude_linter([])

        # No command -> show help
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_help(self):
        """Test that help text shows both modes."""
        result = run_claude_linter(["--help"])

        assert result.exit_code == 0
        assert "pre" in result.output
        assert "post" in result.output
        assert "pre-write hook" in result.output
        assert "post-write hook" in result.output
