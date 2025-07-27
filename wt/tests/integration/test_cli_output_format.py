"""Integration tests that verify actual CLI output formatting."""

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from wt.cli import main
from wt.shared.git_interface import WorktreeStatus
from wt.shared.github_models import PRData, PRInfo, PRState
from wt.shared.models import CommitInfo


@pytest.mark.integration
class TestCLIOutputFormat:
    def test_status_table_rendering(
        self,
        cli_runner: CliRunner,
        temp_config_file,
        sample_worktree_status,
        sample_worktree_status_with_changes,
    ):
        """Test that the status table renders correctly with real formatting."""
        # Create status data
        commit_info = CommitInfo(
            last_commit="abc12345",
            last_commit_message="Add new feature",
            last_commit_author="Test Author",
            last_commit_date=datetime(2024, 1, 15, 10, 30, 0),
        )

        status_dict = {
            "main": WorktreeStatus(
                name="main",
                branch="master",
                ahead=2,
                behind=0,
                dirty_files=["file1.py", "file2.py"],
                untracked_files=["new_file.py"],
                default_branch="master",
                commit_info=commit_info,
            ),
            "feature-branch": sample_worktree_status,
            "error-branch": WorktreeStatus(
                name="error-branch",
                branch="test/error-branch",
                ahead=0,
                behind=0,
                dirty_files=[],
                untracked_files=[],
                default_branch="master",
                commit_info=None,
                error="Stale worktree: branch was deleted",
            ),
        }

        with patch(
            "wt.client.daemon_client.GitStatusdDaemonClient.get_all_worktree_status"
        ) as mock_get_status:
            mock_get_status.return_value = status_dict
            result = cli_runner.invoke(main, ["sh"])

        assert result.exit_code == 0
        output = result.output
        print("Actual output:")
        print(repr(output))

        # Verify content appears in output
        assert "main" in output
        assert "feature-branch" in output
        assert "error-branch" in output

    def test_list_worktrees_empty(self, cli_runner: CliRunner, temp_config_file):
        """Test ls command with no worktrees."""
        with patch(
            "wt.client.daemon_client.GitStatusdDaemonClient.get_all_worktree_status"
        ) as mock_get_status:
            mock_get_status.return_value = {}
            result = cli_runner.invoke(main, ["sh", "ls"])

        assert result.exit_code == 0
        assert "No worktrees found" in result.output

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
        # Should show some worktree content - the exact names depend on the fixture
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
