"""Integration tests for the new CLI architecture."""

from datetime import datetime
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from adgn.wt.cli import main
from adgn.wt.shared.constants import MAIN_WORKTREE_DISPLAY_NAME
from adgn.wt.shared.protocol import (
    CommitInfo,
    DaemonHealth,
    DaemonHealthStatus,
    PRInfoDisabled,
    StatusItem,
    StatusResponse,
    StatusResult,
)


def create_empty_status_response() -> StatusResponse:
    """Create empty StatusResponse for testing."""
    return StatusResponse(
        items={},
        total_processing_time_ms=0.0,
        concurrent_requests=1,
        daemon_health=DaemonHealth(status=DaemonHealthStatus.OK),
    )


def create_test_status_response() -> StatusResponse:
    """Create StatusResponse with test data."""

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

    main_result = StatusResult(
        wtid="main",
        name=MAIN_WORKTREE_DISPLAY_NAME,
        branch_name="main",
        upstream_branch="main",
        absolute_path="/tmp/main",
        has_dirty_files=False,
        has_untracked_files=False,
        ahead_count=0,
        behind_count=0,
        pr_info=PRInfoDisabled(),
        commit_info=test_commit_info,
        processing_time_ms=25.0,
        last_updated_at=datetime.now(),
    )

    return StatusResponse(
        items={
            "test-worktree": StatusItem(status=test_result, processing_time_ms=25.0),
            "main": StatusItem(status=main_result, processing_time_ms=25.0),
        },
        total_processing_time_ms=50.0,
        concurrent_requests=1,
        daemon_health=DaemonHealth(status=DaemonHealthStatus.OK),
    )


@pytest.mark.integration
class TestNewCLIIntegration:
    @patch("wt.client.wt_client.WtClient.get_status")
    def test_default_status_command(
        self,
        mock_get_status,
        cli_test_env,
        monkeypatch,
    ):
        """Test that default command (no args) shows worktree status."""
        mock_get_status.return_value = create_empty_status_response()
        monkeypatch.setenv("WT_DIR", str(cli_test_env))

        result = CliRunner().invoke(main, ["sh"])

        if result.exit_code != 0:
            print(f"CLI output: {result.output}")
            print(f"CLI stderr: {result.stderr_bytes}")
        assert result.exit_code == 0
        assert "No worktrees found" in result.output

    @patch("wt.client.wt_client.WtClient.get_status")
    def test_list_worktrees_command(
        self,
        mock_get_status,
        cli_test_env,
        monkeypatch,
    ):
        """Test ls command works with new CLI."""
        mock_get_status.return_value = create_empty_status_response()
        monkeypatch.setenv("WT_DIR", str(cli_test_env))

        result = CliRunner().invoke(main, ["sh", "ls"])

        assert result.exit_code == 0

    @patch("wt.client.wt_client.WtClient.get_status")
    def test_list_worktrees_with_data(
        self,
        mock_get_status,
        cli_test_env,
        monkeypatch,
    ):
        """Test ls command with actual worktree data."""
        mock_get_status.return_value = create_test_status_response()
        monkeypatch.setenv("WT_DIR", str(cli_test_env))

        result = CliRunner().invoke(main, ["sh", "ls"])

        assert result.exit_code == 0
        # Should show some content about worktrees
        assert len(result.output.strip()) > 0

    def test_help_command(self, cli_test_env, monkeypatch):
        """Test help command works with new CLI."""
        monkeypatch.setenv("WT_DIR", str(cli_test_env))

        result = CliRunner().invoke(main, ["sh", "help"])

        assert result.exit_code == 0
        assert "wt - Enhanced worktree management" in result.output
        assert "USAGE:" in result.output

    def test_help_flag(self, cli_test_env, monkeypatch):
        """Test --help flag works with new CLI."""
        monkeypatch.setenv("WT_DIR", str(cli_test_env))

        result = CliRunner().invoke(main, ["sh", "--help"])

        assert result.exit_code == 0
        assert "USAGE:" in result.output  # Custom help format

    @patch("wt.client.wt_client.WtClient.get_status")
    def test_status_command_with_pr_flag(
        self,
        mock_get_status,
        cli_test_env,
        monkeypatch,
    ):
        """Test status command with --pr flag."""
        mock_get_status.return_value = create_test_status_response()
        monkeypatch.setenv("WT_DIR", str(cli_test_env))

        result = CliRunner().invoke(main, ["sh", "--pr"])

        assert result.exit_code == 0
        assert "test-worktree" in result.output  # from our test data
