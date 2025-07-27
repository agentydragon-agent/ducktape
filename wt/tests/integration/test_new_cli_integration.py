"""Integration tests for the new CLI architecture."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from wt.cli import main


@pytest.mark.integration
class TestNewCLIIntegration:
    def test_default_status_command(
        self, cli_runner: CliRunner, temp_config_file, empty_worktree_status
    ):
        """Test that default command (no args) shows worktree status."""
        with patch(
            "wt.client.daemon_client.GitStatusdDaemonClient.get_all_worktree_status"
        ) as mock_get_status:
            mock_get_status.return_value = empty_worktree_status
            result = cli_runner.invoke(main, ["sh"])

        assert result.exit_code == 0
        assert "No worktrees found" in result.output

    def test_list_worktrees_command(
        self, cli_runner: CliRunner, temp_config_file, empty_worktree_status
    ):
        """Test ls command works with new CLI."""
        with patch(
            "wt.client.daemon_client.GitStatusdDaemonClient.get_all_worktree_status"
        ) as mock_get_status:
            mock_get_status.return_value = empty_worktree_status
            result = cli_runner.invoke(main, ["sh", "ls"])

        assert result.exit_code == 0

    def test_list_worktrees_with_data(
        self, cli_runner: CliRunner, temp_config_file, populated_worktree_status
    ):
        """Test ls command with actual worktree data."""
        with patch(
            "wt.client.daemon_client.GitStatusdDaemonClient.get_all_worktree_status"
        ) as mock_get_status:
            mock_get_status.return_value = populated_worktree_status
            result = cli_runner.invoke(main, ["sh", "ls"])

        assert result.exit_code == 0
        # Should show some content about worktrees
        assert len(result.output.strip()) > 0

    def test_help_command(self, cli_runner: CliRunner, temp_config_file):
        """Test help command works with new CLI."""
        result = cli_runner.invoke(main, ["sh", "help"])

        assert result.exit_code == 0
        assert "wt - Enhanced worktree management" in result.output
        assert "USAGE:" in result.output

    def test_help_flag(self, cli_runner: CliRunner, temp_config_file):
        """Test --help flag works with new CLI."""
        result = cli_runner.invoke(main, ["sh", "--help"])

        assert result.exit_code == 0
        assert "USAGE:" in result.output  # Custom help format

    def test_status_command_with_pr_flag(
        self, cli_runner: CliRunner, temp_config_file, sample_worktree_status
    ):
        """Test status command with --pr flag."""
        status_dict = {"test-wt": sample_worktree_status}

        with patch(
            "wt.client.daemon_client.GitStatusdDaemonClient.get_all_worktree_status"
        ) as mock_get_status:
            mock_get_status.return_value = status_dict
            result = cli_runner.invoke(main, ["sh", "--pr"])

        assert result.exit_code == 0
        assert "test-wt" in result.output  # from our test data
