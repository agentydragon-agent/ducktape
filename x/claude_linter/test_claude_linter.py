"""Unit tests for the unified Claude linter binary."""

import pytest_bazel
from click.testing import CliRunner

from x.claude_linter.cli import cli


def run_claude_linter(args: list[str], input_text: str | None = None):
    """Invoke the claude-linter CLI in-process and capture result."""
    runner = CliRunner()
    return runner.invoke(cli, args, input=input_text)


class TestUnifiedLinter:
    """Test cases for the unified linter entry point."""

    def test_hook_with_invalid_json(self):
        """Test that 'claude-linter hook' fails with invalid JSON."""
        result = run_claude_linter(["hook"], "invalid json")

        # Hook should fail with JSON decode error
        assert result.exit_code == 1
        assert "Invalid JSON input" in result.output

    def test_invalid_command(self):
        """Test that invalid command is rejected."""
        result = run_claude_linter(["invalid"])

        # Should fail with argument error
        assert result.exit_code == 2
        assert "No such command 'invalid'" in result.output

    def test_no_command(self):
        """Test that missing command requires a command."""
        result = run_claude_linter([])

        # No command -> error (CLI requires a subcommand)
        assert result.exit_code == 2
        assert "Usage:" in result.output

    def test_help(self):
        """Test that help text shows available commands."""
        result = run_claude_linter(["--help"])

        assert result.exit_code == 0
        assert "hook" in result.output
        assert "clean" in result.output


if __name__ == "__main__":
    pytest_bazel.main()
