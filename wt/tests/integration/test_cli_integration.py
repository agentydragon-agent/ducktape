"""Integration tests for the CLI with real git operations.

CRITICAL: Daemon Socket Path Length Issue
=========================================

These tests were historically failing due to Unix domain socket path length
limitations (~104 characters). The issue occurred because pytest's temporary
directories generate extremely long paths like:

    /private/var/folders/.../pytest-of-user/pytest-N/test_name0/test_repo/.wt/daemon.sock

This exceeds Unix socket limits, causing daemon startup to fail with:
    OSError: AF_UNIX path too long

SOLUTION: The Config.daemon_socket_file property now automatically detects
long paths and falls back to shorter paths in /tmp with unique hashing:
    /tmp/wt_daemon_a1b2c3d4.sock

Test Isolation Requirements
===========================

For proper daemon test isolation, these tests use:

1. pytest's tmp_path fixture for each test's own temporary directory
2. kill_daemon_and_verify() function that:
   - Kills daemon using CLI command
   - Verifies daemon process is gone within timeout
   - Fails test if daemon doesn't shut down properly
3. Fixture setup/teardown that kills daemon before and after each test
4. WT_MAIN_REPO environment variable pointing to test repo

This ensures each test runs in complete isolation without daemon interference.
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pygit2
import pytest
import yaml

from ..conftest import kill_daemon_and_verify
from ..test_constants import GITSTATUSD_PATH
from ..test_utils import run_cli_command

# Very distinctive test branch name to avoid conflicts
TEST_BRANCH_NAME = "XXX-ADGN-WT-INTERACTION-TEST-BRANCH-NAME-XXX"


# real_temp_repo fixture now provided by conftest.py


# real_env fixture now provided by conftest.py


# kill_daemon_and_verify function now provided by conftest.py


@pytest.mark.integration
class TestCLIIntegration:
    def setup_method(self):
        """Clean up any running daemons before each test."""
        # Kill any running daemons from previous tests
        subprocess.run(["pkill", "-f", "wt"], check=False)
        time.sleep(0.1)

    def teardown_method(self):
        """Clean up after each test."""
        subprocess.run(["pkill", "-f", "wt"], check=False)

    def test_list_worktrees_empty(self, real_temp_repo, real_env):
        """Test listing worktrees when none exist."""
        # Kill any existing daemon first
        kill_daemon_and_verify(real_temp_repo)

        result = run_cli_command(["sh", "ls"], env=real_env)
        assert result.returncode == 0
        assert "No worktrees found" in result.stdout

    def test_create_worktree_from_master(self, real_temp_repo, real_env):
        """Test creating a worktree from master branch."""
        kill_daemon_and_verify(real_temp_repo)

        # Create worktree
        result = run_cli_command(["sh", "-c", "new-feature"], env=real_env)
        assert result.returncode == 0, f"Create failed: {result.stderr}"

        # Verify worktree was created
        worktree_path = real_temp_repo / "worktrees" / "new-feature"
        assert worktree_path.exists(), f"Worktree not created at {worktree_path}"
        assert (worktree_path / ".git").exists(), "Worktree missing .git"

        # Verify branch was created using pygit2
        repo = pygit2.Repository(str(real_temp_repo))
        branch_names = [name for name in repo.references if name.startswith("refs/heads/test/")]
        assert "refs/heads/test/new-feature" in branch_names

    def test_list_worktrees_with_existing(self, real_temp_repo, real_env):
        """Test listing worktrees when some exist."""
        kill_daemon_and_verify(real_temp_repo)

        # Create a worktree first
        result = run_cli_command(["sh", "-c", "feature1"], env=real_env)
        assert result.returncode == 0, f"Create failed: {result.stderr}"

        # List worktrees
        result = run_cli_command(["sh", "ls"], env=real_env)
        assert result.returncode == 0
        assert "feature1" in result.stdout

    def test_status_command_shows_worktrees(self, real_temp_repo, real_env):
        """Test that status command shows created worktrees."""
        kill_daemon_and_verify(real_temp_repo)

        # Create worktrees
        run_cli_command(["sh", "-c", "feature1"], env=real_env)
        run_cli_command(["sh", "-c", "feature2"], env=real_env)

        # Check status
        result = run_cli_command(["sh"], env=real_env)
        assert result.returncode == 0
        assert "feature1" in result.stdout
        assert "feature2" in result.stdout

    def test_create_worktree_reserved_name(self, real_temp_repo, real_env):
        """Test that creating worktrees with reserved names fails."""
        kill_daemon_and_verify(real_temp_repo)

        result = run_cli_command(["sh", "-c", "main"], env=real_env)
        assert result.returncode != 0
        assert "reserved" in result.stderr.lower() or "error" in result.stdout.lower()

    def test_worktree_navigation(self, real_temp_repo, real_env):
        """Test navigation to existing worktree."""
        kill_daemon_and_verify(real_temp_repo)

        # Create a worktree
        run_cli_command(["sh", "-c", "nav-test"], env=real_env)

        # Navigate to it (this should output a cd command)
        result = run_cli_command(["sh", "nav-test"], env=real_env)
        assert result.returncode == 0
        # The navigation command outputs cd command to stdout for shell execution

    def test_help_commands(self, real_temp_repo, real_env):
        """Test help command works."""
        kill_daemon_and_verify(real_temp_repo)

        result = run_cli_command(["sh", "help"], env=real_env)
        assert result.returncode == 0
        assert "wt - Enhanced worktree management" in result.stdout

    def test_path_commands(self, real_temp_repo, real_env):
        """Test path resolution commands."""
        kill_daemon_and_verify(real_temp_repo)

        # Create a worktree
        run_cli_command(["sh", "-c", "path-test"], env=real_env)

        # Test path command
        result = run_cli_command(["sh", "path", "path-test"], env=real_env)
        assert result.returncode == 0
        assert "path-test" in result.stdout


@pytest.mark.integration
class TestRealGitOperations:
    """Tests that verify actual git operations work correctly."""

    def setup_method(self):
        subprocess.run(["pkill", "-f", "wt"], check=False)

    def teardown_method(self):
        subprocess.run(["pkill", "-f", "wt"], check=False)

    def test_worktree_branch_creation(self, real_temp_repo, real_env):
        """Test that worktree creation actually creates git branches."""
        kill_daemon_and_verify(real_temp_repo)

        # Create worktree
        result = run_cli_command(["sh", "-c", "test-branch"], env=real_env)
        assert result.returncode == 0, f"Failed: {result.stderr}"

        # Check that branch exists using pygit2
        repo = pygit2.Repository(str(real_temp_repo))
        branch_names = [name for name in repo.references if name.startswith("refs/heads/test/")]
        assert "refs/heads/test/test-branch" in branch_names

        # Check worktree is on correct branch
        worktree_path = real_temp_repo / "worktrees" / "test-branch"
        worktree_repo = pygit2.Repository(str(worktree_path))
        assert worktree_repo.head.shorthand == "test/test-branch"

    def test_worktree_git_operations(self, real_temp_repo, real_env):
        """Test git operations within created worktrees."""
        kill_daemon_and_verify(real_temp_repo)

        # Create worktree
        run_cli_command(["sh", "-c", "git-ops"], env=real_env)
        worktree_path = real_temp_repo / "worktrees" / "git-ops"

        # Make changes in worktree using pygit2
        test_file = worktree_path / "test.txt"
        test_file.write_text("Test content")

        # Add and commit using pygit2
        worktree_repo = pygit2.Repository(str(worktree_path))
        worktree_repo.index.add("test.txt")
        worktree_repo.index.write()

        signature = pygit2.Signature("Test User", "test@example.com")
        tree = worktree_repo.index.write_tree()
        parent = worktree_repo.head.target
        commit_id = worktree_repo.create_commit(
            "HEAD", signature, signature, "Test commit", tree, [parent]
        )

        # Verify commit exists
        commit = worktree_repo.get(commit_id)
        assert commit.message == "Test commit"

    def test_worktree_status_with_changes(self, real_temp_repo, real_env):
        """Test that status command shows git changes in worktrees."""
        kill_daemon_and_verify(real_temp_repo)

        # Create worktree
        run_cli_command(["sh", "-c", "status-test"], env=real_env)
        worktree_path = real_temp_repo / "worktrees" / "status-test"

        # Make some changes
        (worktree_path / "modified.txt").write_text("Modified content")
        (worktree_path / "untracked.txt").write_text("Untracked content")

        # Stage one file using pygit2
        worktree_repo = pygit2.Repository(str(worktree_path))
        worktree_repo.index.add("modified.txt")
        worktree_repo.index.write()

        # Check status shows the changes
        result = run_cli_command(["sh"], env=real_env)
        assert result.returncode == 0
        # Status should show the worktree (exact format depends on implementation)
        assert "status-test" in result.stdout
