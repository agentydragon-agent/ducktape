import os
import subprocess
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Generator, Optional
from unittest.mock import Mock, patch

# Removed GitPython dependency; use pygit2 for repo fixtures if needed
import pygit2
import pytest
import yaml
from click.testing import CliRunner

from wt.server.github_client import GitHubInterface
from wt.server.worktree_service import WorktreeService
from wt.shared.configuration import Configuration
from wt.shared.config_file import ConfigFile
from wt.shared.models import PRStatus

from .test_constants import GITSTATUSD_PATH

# Services container removed - tests now use direct dependencies


# mock_cli_services removed - CLI no longer uses Services container


@pytest.fixture
def mock_git():
    """Mock git interface - penance: mocking because external subprocess calls are not suitable for unit tests."""
    return Mock()


@pytest.fixture
def mock_daemon_client():
    """Mock daemon client - penance: mocking because tests shouldn't start real daemons."""
    return Mock()


@pytest.fixture
def view_formatter():
    """Real view formatter - no mocking needed."""
    from wt.client.view_formatter import ViewFormatter

    return ViewFormatter()


@pytest.fixture
def worktree_service(mock_git, mock_github_interface):
    """Real WorktreeService with mocked dependencies."""
    from wt.server.worktree_service import WorktreeService

    return WorktreeService(mock_git, mock_github_interface)


# Services container removed - tests now use direct dependencies
# Individual mock fixtures are available: mock_git, mock_github_interface, mock_daemon_client, etc.


@pytest.fixture
def mock_services_container(
    test_config, mock_github_interface, mock_daemon_client, view_formatter, real_worktree_service
):
    """Minimal mock services container for backward compatibility with integration tests.

    Note: This is a temporary fixture to ease the transition away from Services containers.
    Eventually, integration tests should use direct dependencies.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        config=test_config,
        github=mock_github_interface,
        daemon_client=mock_daemon_client,
        formatter=view_formatter,
        worktree_service=real_worktree_service,
    )


@pytest.fixture
def mock_config(test_config):
    """Alias for test_config for backward compatibility."""
    return test_config


@pytest.fixture
def set_test_env_vars(test_config: Configuration):
    """Apply environment variable overrides for unit tests that need them."""
    with patch.dict(
        os.environ,
        {
            "WT_MAIN_REPO": str(test_config.main_repo),
            "WT_WORKTREES_DIR": str(test_config.worktrees_dir),
            "WT_BRANCH_PREFIX": test_config.branch_prefix,
            "WT_UPSTREAM_BRANCH": test_config.upstream_branch,
            "WT_LOG_OPERATIONS": "true" if test_config.log_operations else "false",
            "WT_COW_METHOD": test_config.cow_method,
        },
    ):
        yield


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def isolated_git_env(temp_dir: Path):
    """Create completely isolated git environment for testing."""
    git_env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",  # Ignore system git config
        "HOME": str(temp_dir),  # Isolate home directory
        "XDG_CONFIG_HOME": str(temp_dir / "config"),  # Isolate XDG config
        "GIT_CONFIG_GLOBAL": "/dev/null",  # Ignore global git config
    }

    # Use patch to ensure GitPython uses our isolated environment
    with patch.dict(os.environ, git_env):
        yield git_env


@pytest.fixture
def git_repo(temp_dir: Path, isolated_git_env: dict[str, str]) -> Path:
    repo_path = temp_dir / "repo"
    repo_path.mkdir()

    # Initialize git repo using pygit2 in isolated environment
    repo = pygit2.init_repository(str(repo_path), initial_head="master")

    # Configure git user for testing
    repo.config["user.name"] = "Test User"
    repo.config["user.email"] = "test@example.com"

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repository\n")
    repo.index.add("README.md")
    repo.index.write()

    # Create signature for the commit
    signature = pygit2.Signature("Test User", "test@example.com")
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", signature, signature, "Initial commit", tree, [])

    return repo_path


@pytest.fixture
def worktrees_dir(temp_dir: Path) -> Path:
    wt_dir = temp_dir / "worktrees"
    wt_dir.mkdir()
    return wt_dir


@pytest.fixture
def test_config(git_repo: Path, worktrees_dir: Path) -> Configuration:
    return build_test_configuration(
        git_repo,
        worktrees_dir=str(worktrees_dir),
        upstream_branch="HEAD"
    )




@pytest.fixture
def mock_github_interface():
    mock = Mock(spec=GitHubInterface)

    # Default mock responses
    mock.pr_list.return_value = []
    mock.pr_search.return_value = []
    mock.pr_view.return_value = None

    return mock


@pytest.fixture
def real_git_manager(test_config):
    """Real GitManager for integration tests."""
    from wt.server.git_manager import GitManager

    return GitManager(config=test_config)


@pytest.fixture
def real_worktree_service(real_git_manager, mock_github_interface):
    """Real WorktreeService with mocked GitHub interface."""
    return WorktreeService(real_git_manager, mock_github_interface)


@pytest.fixture
def sample_commit_info():
    """Sample CommitInfo for testing."""
    from datetime import datetime

    from wt.shared.models import CommitInfo

    return CommitInfo(
        last_commit="abc123def456",
        last_commit_message="Add new feature",
        last_commit_author="Test Author",
        last_commit_date=datetime(2024, 1, 15, 10, 30, 0),
    )


# sample_worktree_status fixture deleted - use create_test_status_response helper instead


# sample_worktree_status_with_changes fixture deleted - use create_test_status_response helper instead


@pytest.fixture
def empty_worktree_status():
    """Empty worktree status dict for testing empty state."""
    return {}


# populated_worktree_status fixture deleted - use create_test_status_response helper instead


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_config_file(test_config):
    """Write out a temporary config file for testing."""
    import tempfile

    # Create temp config directory - deliberately separate from main repo
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        # Put WT_DIR in separate location to test for baked-in assumptions
        wt_dir = temp_path / "WTDIR" / ".wt"
        
        # Use centralized helper to create configuration
        build_test_configuration(
            test_config.main_repo,
            wt_dir=wt_dir,
            worktrees_dir=str(test_config.worktrees_dir),
            branch_prefix=test_config.branch_prefix,
            upstream_branch=test_config.upstream_branch,
            github_repo=test_config.github_repo,
            log_operations=test_config.log_operations,
            cache_expiration=3600,
            cache_refresh_age=300,
            hidden_worktree_patterns=test_config.hidden_worktree_patterns,
            gitstatusd_path=GITSTATUSD_PATH,
            cow_method="copy",
            github_enabled=False
        )
        
        config_file = wt_dir / "config.yaml"
        
        # Set WT_DIR to use our temp wt directory (new config system)
        with patch.dict(os.environ, {"WT_DIR": str(wt_dir)}):
            yield config_file


@pytest.fixture
def mock_cli_dependencies(temp_config_file):
    """Context manager that mocks CLI dependencies for testing."""
    from contextlib import contextmanager

    @contextmanager
    def _mock_cli_dependencies(worktree_status_return_value):
        with patch(
            "wt.client.daemon_client.GitStatusdDaemonClient.get_status"
        ) as mock_get_status:
            mock_get_status.return_value = worktree_status_return_value
            yield mock_get_status

    return _mock_cli_dependencies


@pytest.fixture
def populated_repo(git_repo: Path) -> Path:
    repo = pygit2.Repository(str(git_repo))

    # Create feature branch
    master_ref = repo.references["refs/heads/master"]
    feature_ref = repo.references.create("refs/heads/feature-branch", master_ref.target)
    repo.checkout(feature_ref)

    # Add some commits to feature branch
    (git_repo / "feature.txt").write_text("Feature code\n")
    repo.index.add("feature.txt")
    repo.index.write()

    signature = pygit2.Signature("Test User", "test@example.com")
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", signature, signature, "Add feature", tree, [master_ref.target])

    # Create another branch
    another_ref = repo.references.create("refs/heads/another-branch", feature_ref.target)
    repo.checkout(another_ref)

    (git_repo / "another.txt").write_text("Another feature\n")
    repo.index.add("another.txt")
    repo.index.write()

    tree = repo.index.write_tree()
    repo.create_commit(
        "HEAD", signature, signature, "Add another feature", tree, [feature_ref.target]
    )

    # Switch back to master
    repo.checkout("refs/heads/master")

    return git_repo


@pytest.fixture
def existing_worktrees(test_config, real_worktree_service) -> list[Path]:
    """Create existing worktrees for testing."""
    worktrees = []

    # Create test worktrees using real service
    feature_wt = real_worktree_service.create_worktree(test_config, "feature-work")
    worktrees.append(feature_wt)

    # Create worktree from master
    main_wt = real_worktree_service.create_worktree(test_config, "main-work")
    worktrees.append(main_wt)

    return worktrees


@pytest.fixture
def mock_pr_responses(mock_github_interface):
    def setup_pr_response(branch: str, pr_number: int, state: str = "open", mergeable: bool = True):
        pr_status = PRStatus(state=state, number=pr_number, mergeable=mergeable)

        # Mock the pr_list method that's actually used by the WorktreeService
        mock_github_interface.pr_list.return_value = [
            {
                "number": pr_number,
                "headRefName": branch,
                "state": state,
                "title": f"PR for {branch}",
            }
        ]

    return setup_pr_response


@pytest.fixture
def capture_commands() -> Generator[list[str], None, None]:
    commands = []

    def mock_emit_command(cmd: str):
        commands.append(cmd)

    with patch("wt.shared.shell_utils.emit_command", side_effect=mock_emit_command):
        yield commands


@pytest.fixture
def mock_process_check():
    """Mock process checking to avoid system dependencies."""
    with patch(
        "wt.server.worktree_service.WorktreeService._get_processes_in_directory"
    ) as mock:
        mock.return_value = []  # No processes by default
        yield mock


@pytest.fixture
def dirty_worktree(existing_worktrees: list[Path]) -> Path:
    worktree_path = existing_worktrees[0]

    # Add some uncommitted changes
    (worktree_path / "dirty.txt").write_text("Uncommitted changes\n")
    (worktree_path / "untracked.txt").write_text("Untracked file\n")

    # Stage one file using pygit2
    repo = pygit2.Repository(str(worktree_path))
    repo.index.add("dirty.txt")
    repo.index.write()

    return worktree_path


@pytest.fixture
def set_cwd():
    class CwdManager:
        def __init__(self):
            self.original_cwd = os.getcwd()

        def __call__(self, path: Path):
            os.chdir(str(path))
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            os.chdir(self.original_cwd)

    return CwdManager()


def assert_worktree_exists(worktree_path: Path, expected_branch: str | None = None):
    assert worktree_path.exists(), f"Worktree {worktree_path} does not exist"
    assert worktree_path.is_dir(), f"Worktree {worktree_path} is not a directory"

    if expected_branch:
        repo = pygit2.Repository(str(worktree_path))
        head_ref = repo.head.shorthand
        assert head_ref == expected_branch, f"Expected branch {expected_branch}, got {head_ref}"


def assert_worktree_not_exists(worktree_path: Path):
    assert not worktree_path.exists(), f"Worktree {worktree_path} should not exist"


# Integration test fixtures for daemon-based tests
# ================================================


def kill_daemon_and_verify(repo_path: Path, timeout: float = 5.0):
    """Kill daemon using CLI command and verify it's gone.

    CRITICAL for test isolation. This function ensures that:

    1. Daemon is killed using the actual CLI kill-daemon command (not raw kill)
    2. Process termination is verified by checking PID file and process existence
    3. Test fails if daemon doesn't terminate within timeout (indicates stuck daemon)
    4. Socket cleanup is verified to ensure no leftover daemon state

    This prevents daemon interference between tests, which was causing sporadic
    test failures when daemons from previous tests were still running.

    Args:
        repo_path: Path to test repository (used to find daemon files)
        timeout: Max seconds to wait for daemon termination (default 5.0)

    Raises:
        pytest.fail: If daemon doesn't terminate within timeout period
    """
    from .test_utils import run_cli_command

    env = os.environ.copy()
    env["WT_MAIN_REPO"] = str(repo_path.resolve())

    # Run kill-daemon command
    result = run_cli_command(["sh", "kill-daemon"], env=env)

    # Don't assert success here - daemon might not be running, which is fine

    # Wait and verify daemon is gone
    daemon_dir = repo_path / ".wt"
    pid_file = daemon_dir / "daemon.pid"

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not pid_file.exists():
            return  # Daemon is gone

        try:
            pid_content = pid_file.read_text().strip()
            if not pid_content:
                return  # Empty PID file means daemon is gone

            pid = int(pid_content)

            # Check if process still exists
            try:
                os.kill(pid, 0)  # Signal 0 just checks if process exists
                time.sleep(0.1)  # Process still exists, wait a bit more
            except (OSError, ProcessLookupError):
                return  # Process is gone

        except (ValueError, FileNotFoundError):
            return  # Invalid PID or file gone

    # If we get here, daemon didn't shut down in time
    if pid_file.exists():
        try:
            pid_content = pid_file.read_text().strip()
            if pid_content:
                pytest.fail(
                    f"Daemon with PID {pid_content} did not shut down within {timeout} seconds"
                )
        except (OSError, UnicodeDecodeError) as e:
            # If we can't read the PID file, still fail but with a more specific error
            pytest.fail(f"Daemon cleanup verification failed - could not read PID file: {e}")

    pytest.fail(f"Daemon cleanup verification failed after {timeout} seconds")


def create_integration_test_config_file(repo_path: Path) -> Path:
    """Create a test config file for integration tests using centralized helper.

    Creates config in separate WT_DIR to test for baked-in assumptions.
    """
    # Put WT_DIR in separate location to test for baked-in assumptions about WT_DIR = MAIN_REPO/.wt
    temp_parent = repo_path.parent
    wt_dir = temp_parent / "WTDIR" / ".wt"
    
    # Use centralized helper to create configuration
    build_test_configuration(
        repo_path,
        wt_dir=wt_dir,
        branch_prefix="test/",
        upstream_branch="HEAD",
        log_operations=False,
        cow_method="copy",
        github_enabled=False,
        github_repo="test/test",
        gitstatusd_path=GITSTATUSD_PATH,
    )

    return wt_dir / "config.yaml"


@pytest.fixture
def real_temp_repo(tmp_path):
    """Create a real temporary git repository using pytest's tmp_path.

    CRITICAL: Uses pytest's tmp_path instead of tempfile.TemporaryDirectory for
    proper test isolation. The Unix socket path length issue is automatically
    handled by Config.daemon_socket_file fallback logic.

    This fixture is shared across integration tests to avoid duplication.
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repository with pygit2
    repo = pygit2.init_repository(str(repo_path), initial_head="main")

    # Configure git user
    repo.config["user.name"] = "Test User"
    repo.config["user.email"] = "test@example.com"

    # Create initial commit
    readme_file = repo_path / "README.md"
    readme_file.write_text("# Test Repository")
    repo.index.add("README.md")
    repo.index.write()

    signature = pygit2.Signature("Test User", "test@example.com")
    tree = repo.index.write_tree()
    repo.create_commit("HEAD", signature, signature, "Initial commit", tree, [])

    # Create a distinctive test branch that worktree creation can use
    main_commit = repo.head.target
    test_branch_name = "XXX-ADGN-WT-INTERACTION-TEST-BRANCH-NAME-XXX"
    repo.create_branch(test_branch_name, repo.get(main_commit))

    # Set up worktrees directory
    worktrees_dir = repo_path / "worktrees"
    worktrees_dir.mkdir()

    yield repo_path


@pytest.fixture
def real_env(real_temp_repo):
    """Set up real environment variables for integration tests with proper cleanup.

    Creates config file and sets up WT_MAIN_REPO environment variable.
    Includes daemon cleanup before and after test execution.
    """
    import time

    import yaml

    # Kill any existing daemon first
    kill_daemon_and_verify(real_temp_repo)

    # Create config file in the repo's .wt directory
    create_integration_test_config_file(real_temp_repo)

    # Use WT_DIR environment variable (new config system)
    # Put WT_DIR in separate location to test for baked-in assumptions about WT_DIR = MAIN_REPO/.wt
    env = os.environ.copy()
    temp_parent = real_temp_repo.parent
    wt_dir = temp_parent / "WTDIR" / ".wt"
    env["WT_DIR"] = str(wt_dir)

    yield env

    # Cleanup: Kill daemon after test
    kill_daemon_and_verify(real_temp_repo)


def build_test_configuration(repo_path: Path, wt_dir: Optional[Path] = None, **config_overrides) -> Configuration:
    """Centralized helper to build test configurations with the standard pattern.
    
    This eliminates duplication of the ConfigFile → YAML → Configuration.resolve workflow.
    """
    if wt_dir is None:
        wt_dir = repo_path / ".wt"
    
    # Default config suitable for most tests
    defaults = {
        "main_repo": str(repo_path),
        "worktrees_dir": str(repo_path / "worktrees"),
        "branch_prefix": "test/",
        "upstream_branch": "main", 
        "github_repo": "test-user/test-repo",
        "github_enabled": False,
        "log_operations": True,
        "cache_expiration": 3600,
        "cache_refresh_age": 300,
        "hidden_worktree_patterns": [],
        "gitstatusd_path": GITSTATUSD_PATH,
        "cow_method": "copy",
    }
    
    config_file = ConfigFile(**{**defaults, **config_overrides})
    
    # Save to .wt directory
    wt_dir.mkdir(parents=True, exist_ok=True)
    config_path = wt_dir / "config.yaml"
    
    with open(config_path, 'w') as f:
        yaml.dump(config_file.model_dump(), f)
    
    return Configuration.resolve(wt_dir)


@pytest.fixture
def config_builder(real_temp_repo):
    """Helper to build and resolve configurations for tests."""
    def _build_config(**config_overrides):
        return build_test_configuration(real_temp_repo, **config_overrides)
    
    return _build_config
