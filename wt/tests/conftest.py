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
from .test_data import TestData, ConfigPresets
from .mock_factory import MockFactory, ServiceBuilder
from .repo_factory import GitRepoFactory, RepoPresets
from .config_factory import ConfigFactory, ConfigBuilder


# =============================================================================
# Factory Fixtures - Modern pytest pattern for test setup
#
# These factories replace the old pattern of many specific fixtures with
# flexible, parameterizable factories. Use these patterns:
#
# OLD WAY (being phased out):
#   def test_something(git_repo, mock_github_interface):
#       # Uses hard-coded test repo and mock
#
# NEW WAY (preferred):
#   def test_something(repo_factory, mock_factory):
#       repo = repo_factory.create_repo(**RepoPresets.with_branches())
#       github = mock_factory.github_client(pr_list_returns=[...])
#
# Benefits:
# - Explicit test data (no hidden setup)
# - Parameterizable (different configs per test) 
# - Less fixture coupling
# - Easier to understand and maintain
# =============================================================================

@pytest.fixture
def mock_factory():
    """Factory for creating configured mocks with standard behaviors."""
    return MockFactory


@pytest.fixture
def repo_factory(temp_dir, isolated_git_env):
    """Factory for creating git repositories with different configurations."""
    return GitRepoFactory(temp_dir, isolated_git_env)


@pytest.fixture
def config_factory(temp_dir):
    """Factory for creating test configurations with presets and overrides."""
    def _factory_for_repo(repo_path: Path):
        return ConfigFactory(repo_path, temp_dir)
    return _factory_for_repo


# Service builder and env var fixtures removed - configure directly in tests with factories

@pytest.fixture
def cli_test_env(repo_factory, config_factory):
    """Create test environment for CLI integration tests.
    
    Returns the WT_DIR path that can be used with patch.dict for environment setup.
    CLI tests use this to set up proper configuration without external dependencies.
    """
    # Create repo and config using factories
    repo_path = repo_factory.create_repo()
    factory = config_factory(repo_path)
    config = factory.minimal()
    
    # Return the WT_DIR path (the .wt directory)
    return config.wt_dir


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


# Repository fixtures removed - use repo_factory.create_repo() instead




# Mock fixtures removed - use mock_factory directly instead


# Git manager and worktree service fixtures removed - use service_builder instead


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


# Temp config fixtures removed - use config_factory directly instead


# CLI and worktree fixtures removed - use factories directly instead


# PR response fixtures removed - use mock_factory.github_client() with specific behaviors


@pytest.fixture
def capture_commands() -> Generator[list[str], None, None]:
    commands = []

    def mock_emit_command(cmd: str):
        commands.append(cmd)

    with patch("wt.client.shell_utils.emit_command", side_effect=mock_emit_command):
        yield commands


@pytest.fixture
def mock_process_check():
    """Mock process checking to avoid system dependencies."""
    with patch(
        "wt.server.worktree_service.WorktreeService._get_processes_in_directory"
    ) as mock:
        mock.return_value = []  # No processes by default
        yield mock


# Dirty worktree fixture removed - create test state directly in tests


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


# Integration test fixtures removed - use repo_factory and config_factory directly

@pytest.fixture
def real_temp_repo(repo_factory):
    """Create real temporary git repository for integration tests.
    
    Uses modern repo_factory internally but maintains compatibility with
    existing integration tests that need real git repositories.
    """
    return repo_factory.create_repo(name="test_repo")


@pytest.fixture
def real_env(real_temp_repo, config_factory):
    """Set up real environment for integration tests with proper cleanup.
    
    Creates real configuration and environment setup for tests that need
    to interact with actual daemon processes and gitstatusd.
    """
    # Explicit requirement checks
    import shutil
    assert shutil.which("gitstatusd"), "gitstatusd not found on PATH - required for integration tests"
    
    # Kill any existing daemon first
    kill_daemon_and_verify(real_temp_repo)
    
    # Create config using factory pattern
    factory = config_factory(real_temp_repo)
    config = factory.integration(
        gitstatusd_path=GITSTATUSD_PATH
    )
    
    # Set up environment
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)
    
    # Assume package is properly installed and importable
    
    yield env
    
    # Cleanup: Kill daemon after test
    kill_daemon_and_verify(real_temp_repo)


@pytest.fixture
def real_env_with_existing_worktrees(real_temp_repo, config_factory):
    """Set up real environment with pre-created worktrees for complex tests."""
    # Explicit requirement checks
    import shutil
    assert shutil.which("gitstatusd"), "gitstatusd not found on PATH - required for integration tests"
    
    # Kill any existing daemon first
    kill_daemon_and_verify(real_temp_repo)
    
    # Create config using factory pattern
    factory = config_factory(real_temp_repo) 
    config = factory.integration(
        gitstatusd_path=GITSTATUSD_PATH
    )
    
    # Create some test worktrees using real worktree service
    from wt.server.git_manager import GitManager
    from wt.server.worktree_service import WorktreeService
    
    git_manager = GitManager(config=config)
    github_mock = Mock()  # GitHub not needed for worktree creation
    worktree_service = WorktreeService(git_manager, github_mock)
    
    # Create a couple of test worktrees
    worktree_service.create_worktree(config, "existing-1")
    worktree_service.create_worktree(config, "existing-2")
    
    # Set up environment
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)
    
    # Assume package is properly installed and importable
    
    yield env
    
    # Cleanup: Kill daemon after test
    kill_daemon_and_verify(real_temp_repo)


@pytest.fixture
def test_config(repo_factory, config_factory) -> Configuration:
    """Create test configuration for simple unit tests.
    
    Uses modern factory pattern internally but maintains compatibility
    with existing tests that need basic configuration.
    """
    repo_path = repo_factory.create_repo()
    factory = config_factory(repo_path)
    return factory.minimal(upstream_branch="main")


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


# Config builder fixture removed - use config_factory directly
