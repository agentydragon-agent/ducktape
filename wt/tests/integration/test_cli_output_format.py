"""Integration tests that verify actual CLI output formatting."""

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from wt.cli import main
from wt.shared.protocol import StatusResult, StatusResponse, WorktreeID, CommitInfo
from wt.shared.github_models import PRData, PRInfo, PRState


def create_test_status_response(results_dict=None):
    """Helper to create StatusResponse for testing."""
    if results_dict is None:
        results_dict = {}
    
    return StatusResponse(
        results=results_dict,
        total_processing_time_ms=sum(r.processing_time_ms for r in results_dict.values()) if results_dict else 0.0,
        daemon_health={
            "status": "ok",
            "last_error": None,
            "last_error_time": None,
            "github_errors": 0,
            "gitstatusd_errors": 0,
        },
    )


@pytest.fixture
def cli_runner_with_env(cli_runner, cli_test_env, monkeypatch):
    """Factory fixture for running CLI with mocked environment."""
    def _run_with_mocked_status(status_response, cli_args, mock_get_status):
        """Run CLI with mocked status response and proper environment setup."""
        monkeypatch.setenv("WT_DIR", str(cli_test_env))
        mock_get_status.return_value = status_response
        return cli_runner.invoke(main, cli_args)
    
    return _run_with_mocked_status


@pytest.mark.integration
class TestCLIOutputFormat:
    @patch("wt.client.wt_client.WtClient.get_status")
    def test_status_table_rendering(
        self,
        mock_get_status,
        cli_runner_with_env,
    ):
        """Test that the status table renders correctly with real formatting."""
        # Create status data
        commit_info = CommitInfo(
            hash="abcdef1234567890abcdef1234567890abcdef12",
            short_hash="abcdef12",
            message="Add new feature",
            author="Test Author",
            date="2024-01-15T10:30:00",
        )

        # Create test results
        results = {
            WorktreeID("wtid:main"): StatusResult(
                wtid=WorktreeID("wtid:main"),
                name="main",
                absolute_path="/test/main",
                branch_name="master",
                has_dirty_files=True,
                has_untracked_files=True,
                processing_time_ms=10.0,
                last_updated_at=datetime.now(),
                commit_info=commit_info,
                ahead_count=2,
                behind_count=0,
                is_main=True,
                upstream_branch="master",
            ),
            WorktreeID("wtid:feature-branch"): StatusResult(
                wtid=WorktreeID("wtid:feature-branch"),
                name="feature-branch",
                absolute_path="/test/feature-branch",
                branch_name="feature/test",
                has_dirty_files=False,
                has_untracked_files=False,
                processing_time_ms=8.0,
                last_updated_at=datetime.now(),
                commit_info=commit_info,
                ahead_count=1,
                behind_count=0,
                is_main=False,
                upstream_branch="master",
            ),
        }
        
        status_response = create_test_status_response(results)
        result = cli_runner_with_env(status_response, ["sh"], mock_get_status)

        print("Exit code:", result.exit_code)
        print("Output:", repr(result.output))
        print("Exception:", result.exception if result.exception else "None")
        assert result.exit_code == 0
        output = result.output

        # Verify content appears in output
        assert "main" in output
        assert "feature-branch" in output

    @patch("wt.client.wt_client.WtClient.get_status")
    def test_list_worktrees_empty(self, mock_get_status, cli_runner_with_env):
        """Test ls command with no worktrees."""
        status_response = create_test_status_response({})
        result = cli_runner_with_env(status_response, ["sh", "ls"], mock_get_status)

        assert result.exit_code == 0
        assert "No worktrees found" in result.output

    @patch("wt.client.wt_client.WtClient.get_status")
    def test_list_worktrees_with_data(
        self, mock_get_status, cli_runner_with_env
    ):
        """Test ls command with actual worktree data."""
        # Create test results
        results = {
            WorktreeID("wtid:test1"): StatusResult(
                wtid=WorktreeID("wtid:test1"),
                name="test1",
                absolute_path="/test/test1",
                branch_name="test/test1",
                has_dirty_files=False,
                has_untracked_files=False,
                processing_time_ms=5.0,
                last_updated_at=datetime.now(),
                commit_info=CommitInfo(
                    hash="abc123",
                    short_hash="abc123",
                    message="Test commit",
                    author="Test Author",
                    date="2024-01-01T00:00:00",
                ),
                ahead_count=0,
                behind_count=0,
                is_main=False,
                upstream_branch="master",
            ),
        }
        
        status_response = create_test_status_response(results)
        result = cli_runner_with_env(status_response, ["sh", "ls"], mock_get_status)

        assert result.exit_code == 0
        # Should show some worktree content
        assert len(result.output.strip()) > 0

    def test_help_command(self, cli_runner_with_env, monkeypatch, cli_test_env):
        """Test help command works with new CLI."""
        monkeypatch.setenv("WT_DIR", str(cli_test_env))
        from click.testing import CliRunner
        result = CliRunner().invoke(main, ["sh", "help"])

        assert result.exit_code == 0
        assert "wt - Enhanced worktree management" in result.output
        assert "USAGE:" in result.output

    def test_help_flag(self, cli_runner_with_env, monkeypatch, cli_test_env):
        """Test --help flag works with new CLI."""
        monkeypatch.setenv("WT_DIR", str(cli_test_env))
        from click.testing import CliRunner
        result = CliRunner().invoke(main, ["sh", "--help"])

        assert result.exit_code == 0
        assert "USAGE:" in result.output  # Custom help format
