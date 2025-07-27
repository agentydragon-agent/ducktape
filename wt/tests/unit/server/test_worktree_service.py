"""Unit tests for WorktreeService - pure business logic."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from wt.server.worktree_service import WorktreeService
from wt.shared.git_interface import NoSuchRef, WorktreeStatus
from wt.shared.models import CommitInfo


class TestWorktreeService:
    """Test the WorktreeService in isolation."""

    @pytest.fixture
    def mock_git(self):
        """Mock GitInterface."""
        mock = Mock()
        mock.worktree_list.return_value = "worktree /path/test\nbranch test-branch"
        mock.parse_worktree_list.return_value = [(Path("/path/test"), "test-branch")]
        mock.verify_branch_exists.return_value = None
        mock.rev_count.return_value = 0
        mock.log_format.return_value = "abc123|Test commit|Test Author|2024-01-01T12:00:00"
        return mock

    @pytest.fixture
    def mock_github(self):
        """Mock GitHubInterface."""
        return Mock()

    @pytest.fixture
    def unit_test_config(self, git_repo, tmp_path):
        """Real Configuration object for unit tests."""
        from wt.shared.configuration import Configuration
        from wt.shared.config_file import ConfigFile
        from wt.shared.directories import Directories

        # Use real git repo and tmp_path for test isolation
        worktrees_dir = git_repo / "worktrees"
        worktrees_dir.mkdir(exist_ok=True)

        # Create real Directories instance and override private attributes to point to test tmpdir
        dirs = Directories("test-adgn-worktree")
        dirs._log_dir = tmp_path / "logs"
        dirs._data_dir = tmp_path / "data"

        # Create the directories
        dirs._log_dir.mkdir(parents=True, exist_ok=True)
        dirs._data_dir.mkdir(parents=True, exist_ok=True)

        config_file = ConfigFile(
            worktrees_dir=str(worktrees_dir),
            branch_prefix="test/",
            default_worktree_base_branch="HEAD",
            github_repo="test-user/test-repo",
        )
        return Configuration(config_file, dirs)

    @pytest.fixture
    def service(self, mock_git, mock_github):
        """Create WorktreeService with mocked dependencies."""
        return WorktreeService(mock_git, mock_github)

    def test_list_worktrees_basic(self, service, mock_git, unit_test_config):
        """Test basic worktree listing."""
        # Use real config paths for mock data
        test_worktree_path = unit_test_config.worktrees_dir / "test"
        mock_git.parse_worktree_list.return_value = [(test_worktree_path, "test-branch")]

        result = service.list_worktrees(unit_test_config)

        assert len(result) == 1
        name, path, exists = result[0]
        assert name == "test"
        assert path == test_worktree_path
        mock_git.worktree_list.assert_called_once()
        mock_git.parse_worktree_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_all_worktree_status_basic(self, service, mock_git, unit_test_config):
        """Test getting status for all worktrees."""
        # Mock daemon client
        mock_daemon_client = Mock()

        # Create expected status
        from datetime import datetime

        from wt.shared.git_interface import WorktreeStatus
        from wt.shared.models import CommitInfo

        commit_info = CommitInfo(
            last_commit="abc123",
            last_commit_message="Test commit",
            last_commit_author="Test Author",
            last_commit_date=datetime.now(),
        )

        expected_status = WorktreeStatus(
            name="test",
            branch="test-branch",
            ahead=0,
            behind=0,
            dirty_files=[],
            untracked_files=[],
            default_branch="master",
            commit_info=commit_info,
            error=None,
        )

        # Mock daemon client to return expected status as coroutine
        async def mock_get_status():
            return {"test": expected_status}

        mock_daemon_client.get_all_worktree_status = mock_get_status

        status_dict = await service.get_all_worktree_status_daemon(
            unit_test_config, mock_daemon_client
        )

        assert len(status_dict) == 1
        assert "test" in status_dict
        status = status_dict["test"]
        assert isinstance(status, WorktreeStatus)
        assert status.branch == "test-branch"

    @pytest.mark.asyncio
    async def test_get_all_worktree_status_with_pr(
        self, service, mock_git, mock_github, unit_test_config, set_test_env_vars
    ):
        """Test getting status with PR information."""
        # Mock daemon client
        mock_daemon_client = Mock()

        # Create expected status with PR info
        from datetime import datetime

        from wt.shared.git_interface import WorktreeStatus
        from wt.shared.github_models import PRData, PRInfo, PRState
        from wt.shared.models import CommitInfo

        commit_info = CommitInfo(
            last_commit="abc123",
            last_commit_message="Test commit",
            last_commit_author="Test Author",
            last_commit_date=datetime.now(),
        )

        pr_data = PRData(pr_number=123, pr_state=PRState.OPEN)

        pr_info = PRInfo(branch="test-branch", pr_data=pr_data)

        expected_status = WorktreeStatus(
            name="test",
            branch="test-branch",
            ahead=0,
            behind=0,
            dirty_files=[],
            untracked_files=[],
            default_branch="master",
            commit_info=commit_info,
            error=None,
            pr_info=pr_info,
        )

        # Mock daemon client to return expected status as coroutine
        async def mock_get_status():
            return {"test": expected_status}

        mock_daemon_client.get_all_worktree_status = mock_get_status

        status_dict = await service.get_all_worktree_status_daemon(
            unit_test_config, mock_daemon_client
        )

        # Should still work (PR logic handled by daemon)
        assert len(status_dict) == 1

    def test_create_worktree_status_success(self, service, mock_git):
        """Test successful worktree status creation."""
        status = service._create_worktree_status(
            "test", Path("/path/test"), "test-branch", "master"
        )

        assert status.name == "test"
        assert status.branch == "test-branch"
        assert status.ahead == 0
        assert status.behind == 0
        assert status.dirty_files == []
        assert status.untracked_files == []
        assert status.commit_info is not None

        mock_git.verify_branch_exists.assert_called_with("test-branch")
        mock_git.rev_count.assert_called()

    def test_create_worktree_status_stale_branch(self, service, mock_git):
        """Test handling of stale worktree (branch deleted)."""
        mock_git.verify_branch_exists.side_effect = NoSuchRef("Branch not found")

        with pytest.raises(
            RuntimeError, match="Stale worktree test: branch test-branch was deleted"
        ):
            service._create_worktree_status("test", Path("/path/test"), "test-branch", "master")

    def test_get_commit_info_success(self, service, mock_git):
        """Test successful commit info retrieval."""
        commit_info = service._get_commit_info("test-branch")

        assert commit_info is not None
        assert commit_info.last_commit == "abc123"
        assert commit_info.last_commit_message == "Test commit"
        assert commit_info.last_commit_author == "Test Author"

        mock_git.log_format.assert_called_with("test-branch", "%H|%s|%an|%ai")

    def test_get_commit_info_failure(self, service, mock_git):
        """Test commit info retrieval failure."""
        from wt.shared.git_interface import GitError

        mock_git.log_format.side_effect = GitError("Git command failed")

        commit_info = service._get_commit_info("test-branch")
        assert commit_info is None

    def test_is_managed_worktree_main_repo(self, service, unit_test_config):
        """Test that main repo is not considered managed."""
        result = service._is_managed_worktree(unit_test_config.main_repo, unit_test_config)
        assert not result

    def test_is_managed_worktree_outside_managed_dir(self, service, unit_test_config):
        """Test that worktrees outside managed directory are not considered managed."""
        outside_path = Path("/some/other/path")
        result = service._is_managed_worktree(outside_path, unit_test_config)
        assert not result

    def test_is_managed_worktree_hidden_pattern(self, service, unit_test_config):
        """Test that worktrees matching hidden patterns are not considered managed."""
        # Create a config with specific hidden patterns for this test
        test_config = unit_test_config.model_copy(update={"hidden_worktree_patterns": [".brix-"]})

        hidden_worktree = test_config.worktrees_dir / ".brix-worker-123"
        result = service._is_managed_worktree(hidden_worktree, test_config)
        assert not result

    def test_is_managed_worktree_valid(self, service, unit_test_config):
        """Test that valid worktrees in managed directory are considered managed."""
        valid_worktree = unit_test_config.worktrees_dir / "feature-branch"
        result = service._is_managed_worktree(valid_worktree, unit_test_config)
        assert result

    def test_create_error_status(self, service):
        """Test creating error status for failed worktrees."""
        error_status = service._create_error_status(
            "test", "test-branch", "Branch deleted", "master"
        )

        assert error_status.name == "test"
        assert error_status.branch == "test-branch"
        assert error_status.error == "Branch deleted"
        assert error_status.default_branch == "master"
        assert error_status.ahead == 0
        assert error_status.behind == 0
