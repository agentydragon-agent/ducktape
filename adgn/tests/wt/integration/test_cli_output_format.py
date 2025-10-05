"""Integration tests that verify actual CLI output formatting."""

from datetime import datetime
from unittest.mock import patch

from hamcrest import assert_that, contains_string
import pytest

from adgn.wt.cli import app
from adgn.wt.shared.protocol import (
    CommitInfo,
    StatusResult,
    WorktreeID,
)


@pytest.fixture
def cli_runner_with_env(cli_runner, wt_env):
    """Factory fixture for running CLI with mocked environment."""

    def _run_with_mocked_status(status_response, cli_args, mock_get_status):
        """Run CLI with mocked status response and proper environment setup."""
        mock_get_status.return_value = status_response
        return cli_runner.invoke(app, cli_args)

    return _run_with_mocked_status


@pytest.mark.integration
class TestCLIOutputFormat:
    @patch("adgn.wt.client.wt_client.WtClient.get_status")
    def test_status_table_rendering(
        self,
        mock_get_status,
        cli_runner_with_env,
        build_status_response,
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

        status_response = build_status_response(results)
        result = cli_runner_with_env(status_response, [], mock_get_status)

        assert result.exit_code == 0
        output = result.output

        # Verify content appears in output
        assert_that(output, contains_string("main"))
        assert_that(output, contains_string("feature-branch"))

    @patch("adgn.wt.client.wt_client.WtClient.get_status")
    def test_status_unknown_when_not_cached(
        self, mock_get_status, cli_runner_with_env, build_status_response
    ):
        """When status isn't cached yet, show 'unknown' instead of 'clean'."""
        commit_info = CommitInfo(
            hash="abcdef1234567890abcdef1234567890abcdef12",
            short_hash="abcdef12",
            message="Init",
            author="Test",
            date="2024-01-15T10:30:00",
        )
        results = {
            WorktreeID("wtid:test1"): StatusResult(
                wtid=WorktreeID("wtid:test1"),
                name="test1",
                absolute_path="/test/test1",
                branch_name="test/test1",
                has_dirty_files=False,
                has_untracked_files=False,
                processing_time_ms=1.0,
                last_updated_at=datetime.now(),
                commit_info=commit_info,
                ahead_count=0,
                behind_count=0,
                is_main=False,
                upstream_branch="master",
                is_cached=False,
            ),
        }
        status_response = build_status_response(results)
        result = cli_runner_with_env(status_response, [], mock_get_status)
        assert result.exit_code == 0
        assert_that(result.output, contains_string("unknown"))
