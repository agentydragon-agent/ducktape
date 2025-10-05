"""Integration tests for the new Click-based CLI entry points (no daemon).

These tests use Click's CliRunner with patched WtClient methods.
"""

from datetime import datetime
from unittest.mock import patch

from hamcrest import assert_that, contains_string
import pytest
from typer.testing import CliRunner

from adgn.wt.cli import app
from adgn.wt.shared.protocol import (
    CommitInfo,
    PRInfoDisabled,
    StatusResult,
    WorktreeInfo,
    WorktreeListResult,
)


@pytest.mark.integration
class TestNewCLIIntegration:
    @patch("adgn.wt.client.wt_client.WtClient.get_status")
    def test_default_status_command(
        self,
        mock_get_status,
        wt_env,
        build_status_response,
    ):
        """Test that default command (no args) shows worktree status."""
        mock_get_status.return_value = build_status_response({})

        result = CliRunner().invoke(app, [])

        assert result.exit_code == 0
        assert_that(result.output, contains_string("No worktrees found"))

    @patch("adgn.wt.client.wt_client.WtClient.list_worktrees")
    def test_list_worktrees_command(
        self,
        mock_list,
        wt_env,
        build_status_response,
    ):
        """Test ls command works with new CLI."""
        mock_list.return_value = WorktreeListResult(worktrees=[])

        result = CliRunner().invoke(app, ["ls"])

        assert result.exit_code == 0

    @patch("adgn.wt.client.wt_client.WtClient.list_worktrees")
    def test_list_worktrees_with_data(
        self,
        mock_list,
        wt_env,
        build_status_response,
    ):
        """Test ls command with actual worktree data."""
        test_commit_info = CommitInfo(
            hash="abc123def456",
            short_hash="abc123de",
            message="Test commit",
            author="Test Author",
            date="2024-01-15T10:30:00",
        )
        _test_result = StatusResult(
            wtid="test-worktree",
            name="test-worktree",
            branch_name="test/test-branch",
            upstream_branch="main",
            absolute_path="/tmp/test-worktree",
            has_dirty_files=False,
            has_untracked_files=False,
            ahead_count=0,
            behind_count=0,
            pr_info=PRInfoDisabled(),
            commit_info=test_commit_info,
            processing_time_ms=25.0,
            last_updated_at=datetime.now(),
        )
        mock_list.return_value = WorktreeListResult(
            worktrees=[
                WorktreeInfo(
                    wtid="test-worktree",
                    name="test-worktree",
                    absolute_path="/tmp/test-worktree",
                    branch_name="test/test-branch",
                    exists=True,
                    is_main=False,
                )
            ]
        )

        result = CliRunner().invoke(app, ["ls"])

        assert result.exit_code == 0
        # Should list the mocked worktree we provided
        assert_that(result.output, contains_string("test-worktree"))

    def test_help_command(self, wt_env):
        """Test help command works with new CLI."""

        result = CliRunner().invoke(app, ["help"])

        assert result.exit_code == 0
        assert_that(result.output, contains_string("wt - Enhanced worktree management"))
        assert_that(result.output, contains_string("USAGE:"))

    def test_help_flag(self, wt_env):
        """Test --help flag works with new CLI."""

        result = CliRunner().invoke(app, ["--help"])

        assert result.exit_code == 0
        # Click default help uses 'Usage:'; keep strict
        assert_that(result.output, contains_string("Usage:"))

    @patch("adgn.wt.client.wt_client.WtClient.get_status")
    def test_status_command_with_pr_flag(
        self,
        mock_get_status,
        wt_env,
        build_status_response,
    ):
        """Test status command with --pr flag."""
        test_commit_info = CommitInfo(
            hash="abc123def456",
            short_hash="abc123de",
            message="Test commit",
            author="Test Author",
            date="2024-01-15T10:30:00",
        )
        test_result = StatusResult(
            wtid="test-worktree",
            name="test-worktree",
            branch_name="test/test-branch",
            upstream_branch="main",
            absolute_path="/tmp/test-worktree",
            has_dirty_files=False,
            has_untracked_files=False,
            ahead_count=0,
            behind_count=0,
            pr_info=PRInfoDisabled(),
            commit_info=test_commit_info,
            processing_time_ms=25.0,
            last_updated_at=datetime.now(),
        )
        mock_get_status.return_value = build_status_response({"test-worktree": test_result})

        result = CliRunner().invoke(app, [])

        assert result.exit_code == 0
        assert_that(result.output, contains_string("test-worktree"))
