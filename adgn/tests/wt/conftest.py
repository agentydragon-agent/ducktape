import contextlib
import importlib.util
import io
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pygit2
import pytest
import yaml
from click.testing import CliRunner

from adgn.wt.server import github_client
from adgn.wt.server.git_manager import GitManager
from adgn.wt.server.worktree_service import WorktreeService
from adgn.wt.shared.config_file import ConfigFile
from adgn.wt.shared.configuration import Configuration
from adgn.wt.shared.models import CommitInfo
from adgn.wt.shell.install import main as emit_function

from .config_factory import ConfigFactory
from .mock_factory import MockFactory
from .repo_factory import GitRepoFactory


@pytest.fixture(scope="session", autouse=True)
def _project_root_on_pythonpath():
    project_root = str(Path(__file__).resolve().parents[1])
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = (
        f"{project_root}:{existing}" if existing else project_root
    )
    os.environ["WT_TEST_MODE"] = "1"


@pytest.fixture(autouse=True)
def _disable_gh_cli_token(monkeypatch):
    """Disable gh CLI token retrieval in all tests by default.

    Tests that truly need real GitHub should explicitly bypass or override this.
    """
    monkeypatch.setattr(github_client, "get_github_token", lambda *a, **kw: None)


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


@pytest.fixture(name="ServiceBuilder")
def service_builder():
    """Fixture exposing the ServiceBuilder factory used by tests.

    Tests that previously imported ServiceBuilder from tests.mock_factory can now
    accept a ServiceBuilder fixture parameter to receive the factory class.
    """
    from adgn.tests.wt.mock_factory import ServiceBuilder as _ServiceBuilder

    return _ServiceBuilder


@pytest.fixture(name="TestData")
def test_data():
    """Fixture exposing the TestData constants class.

    Tests that previously imported TestData from tests.test_data can now
    request a TestData fixture parameter to receive the class.
    """
    from adgn.tests.wt.test_data import TestData as _TestData

    return _TestData


@pytest.fixture
def repo_factory(temp_dir):
    """Factory for creating git repositories with different configurations."""
    return GitRepoFactory(temp_dir)


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
def sample_commit_info():
    """Sample CommitInfo for testing."""

    return CommitInfo(
        last_commit="abc123def456",
        last_commit_message="Add new feature",
        last_commit_author="Test Author",
        last_commit_date=datetime(2024, 1, 15, 10, 30, 0),
    )


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def assert_worktree_exists(worktree_path: Path, expected_branch: str | None = None):
    assert worktree_path.exists(), f"Worktree {worktree_path} does not exist"
    assert worktree_path.is_dir(), f"Worktree {worktree_path} is not a directory"

    if expected_branch:
        repo = pygit2.Repository(str(worktree_path))
        head_ref = repo.head.shorthand
        assert head_ref == expected_branch, (
            f"Expected branch {expected_branch}, got {head_ref}"
        )


def assert_worktree_not_exists(worktree_path: Path):
    assert not worktree_path.exists(), f"Worktree {worktree_path} should not exist"


# Integration test fixtures for daemon-based tests
# ================================================


def kill_daemon_at_wt_dir(wt_dir: Path) -> None:
    """Cleanly stop daemon for WT_DIR and assert no leftovers.

    Policy for parallel isolation:
    - Only perform clean shutdown via CLI RPC (no PID signals here)
    - Wait briefly for pid/socket removal
    - If leftovers remain, raise AssertionError to surface leaks early
    """

    pid_file = wt_dir / "daemon.pid"
    sock_file = wt_dir / "daemon.sock"

    # If nothing suggests a running daemon, nothing to do
    if not pid_file.exists() and not sock_file.exists():
        return

    env = os.environ.copy()
    env["WT_DIR"] = str(wt_dir)

    # Attempt graceful shutdown via CLI (succeeds even if daemon already gone)
    try:
        result = subprocess.run(
            ["python3", "-m", "wt.cli", "sh", "kill-daemon"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
            env=env,
        )
    except Exception as e:
        # Don't attempt any PID-based killing here; surface error
        raise AssertionError(f"kill-daemon invocation failed for {wt_dir}: {e}")

    # Wait up to ~1s for files to be removed by daemon shutdown
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if not pid_file.exists() and not sock_file.exists():
            return
        time.sleep(0.05)

    # If still present, declare failure (leak); do not unlink to preserve evidence
    details = (result.stdout or "") + ("\n" + (result.stderr or ""))
    raise AssertionError(
        f"Daemon did not shut down cleanly for {wt_dir}. Leftovers: "
        f"pid_exists={pid_file.exists()} sock_exists={sock_file.exists()}\n{details}",
    )


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
    )

    return wt_dir / "config.yaml"


@pytest.fixture(scope="session", autouse=True)
def _require_gitstatusd_on_path():
    assert shutil.which("gitstatusd"), "integration tests require gitstatusd on PATH"


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

    The hermetic git environment is applied globally by autouse fixture.
    """
    # Create config using factory pattern
    factory = config_factory(real_temp_repo)
    config = factory.integration(github_enabled=False)

    # Ensure clean daemon state for this WT_DIR
    kill_daemon_at_wt_dir(config.wt_dir)

    # Set up environment
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)

    yield env

    # Cleanup: Kill daemon after test
    kill_daemon_at_wt_dir(config.wt_dir)


@pytest.fixture
def real_env_with_existing_worktrees(real_temp_repo, config_factory):
    """Set up real environment with pre-created worktrees for complex tests."""
    # Create config using factory pattern
    factory = config_factory(real_temp_repo)
    config = factory.integration(github_enabled=False)

    # Ensure clean daemon state for this WT_DIR before creating worktrees
    kill_daemon_at_wt_dir(config.wt_dir)

    # Create some test worktrees using real worktree service

    git_manager = GitManager(config=config)
    github_mock = Mock()  # GitHub not needed for worktree creation
    worktree_service = WorktreeService(git_manager, github_mock)

    # Create a couple of test worktrees
    worktree_service.create_worktree(config, "existing-1")
    worktree_service.create_worktree(config, "existing-2")

    # Set up environment
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)

    yield env

    # Cleanup: Kill daemon after test
    kill_daemon_at_wt_dir(config.wt_dir)


@pytest.fixture
def test_config(repo_factory, config_factory) -> Configuration:
    """Create test configuration for simple unit tests.

    Uses modern factory pattern internally but maintains compatibility
    with existing tests that need basic configuration.
    """
    repo_path = repo_factory.create_repo()
    factory = config_factory(repo_path)
    return factory.minimal(upstream_branch="main")


def build_test_configuration(
    repo_path: Path,
    wt_dir: Path | None = None,
    **config_overrides,
) -> Configuration:
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
        "gitstatusd_path": None,
        "cow_method": "copy",
    }

    config_file = ConfigFile(**{**defaults, **config_overrides})

    # Save to .wt directory
    wt_dir.mkdir(parents=True, exist_ok=True)
    config_path = wt_dir / "config.yaml"

    config_path.write_text(yaml.dump(config_file.model_dump()), encoding="utf-8")

    return Configuration.resolve(wt_dir)


# Apply hermetic git environment to every test to prevent leakage from user/system config
# Ensures subprocesses inherit HOME/XDG/GIT_* isolation unless a test explicitly overrides
@pytest.fixture(autouse=True)
def _apply_isolated_git_env(tmp_path: Path, monkeypatch):
    """Apply hermetic git environment per test to prevent leakage.

    Sets HOME/XDG_CONFIG_HOME; GIT_* vars are set via pytest config.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture
def shell_runner():
    """Factory for running shell commands via the installed wt shell function."""

    class ShellRunner:
        def run_script(
            self,
            script_content: str,
            *,
            cwd: Path,
            env: dict[str, str] | None = None,
        ):
            assert importlib.util.find_spec("wt"), (
                "wt package not installed - required for shell integration tests"
            )
            # Ensure env is a copy
            env = os.environ.copy() if env is None else env.copy()

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                emit_function()
            wt_fn = buf.getvalue()

            full_script = f"""#!/bin/bash
# Install wt function via builtin
{wt_fn}

# Original script content
{script_content}
"""
            with tempfile.NamedTemporaryFile(mode="w", suffix=".sh") as f:
                f.write(full_script)
                f.flush()
                Path(f.name).chmod(0o755)
                return subprocess.run(
                    ["/bin/bash", f.name],
                    capture_output=True,
                    text=True,
                    cwd=str(cwd),
                    env=env,
                    check=False,
                )

        def run_argv(
            self,
            *,
            cwd: Path,
            argv: list[str],
            env: dict[str, str] | None = None,
        ):
            return self.run_script(shlex.join(argv), cwd=cwd, env=env)

        def run_wt(
            self,
            *,
            main_repo: Path,
            wt_args: list[str],
            env: dict[str, str] | None = None,
        ):
            return self.run_argv(cwd=main_repo, argv=["wt", *wt_args], env=env)

    return ShellRunner()
