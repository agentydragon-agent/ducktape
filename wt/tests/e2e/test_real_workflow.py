"""Real integration test - runs actual unmodified CLI against temporary repo.

CRITICAL: Unix Socket Path Length Issue & Solution
==================================================

These E2E tests were failing because the daemon couldn't start due to Unix domain
socket path length limitations. The root cause was pytest temporary directories
generating paths like:

    /private/var/folders/_l/vpt0hb254j1f6nyp0qx84hzw0000gp/T/pytest-of-mpokorny/
    pytest-12/test_real_daemon_startup_and_k0/test_repo/.wt/daemon.sock

This path (160+ characters) exceeds the Unix socket limit (~104 chars), causing:
    OSError: AF_UNIX path too long

SOLUTION: Config.daemon_socket_file now automatically detects long paths and
uses shorter alternatives in /tmp with MD5 hashing for uniqueness:
    /tmp/wt_daemon_a1b2c3d4.sock

Historical Debug Process
========================

The fix was discovered by examining daemon.log files in pytest temp directories:
    find /private/var/folders -name "daemon.log" -mmin -10

The logs clearly showed the daemon starting successfully but immediately failing
on socket creation. This is a common issue when running daemon tests with pytest.

Test Architecture
=================

These tests use proper isolation patterns:
- pytest's tmp_path fixture (not tempfile.TemporaryDirectory)
- kill_daemon_and_verify() with timeout-based verification
- Fixture teardown that ensures daemon cleanup
- ADGN_MAIN_REPO env var for config discovery
- Absolute path validation (no relative paths allowed)

The tests run the actual CLI binary end-to-end, making them true integration tests
that catch real-world deployment issues like this socket path problem.
"""

import os
import subprocess
import time
from pathlib import Path

import pygit2
import pytest
import yaml

from ..conftest import create_integration_test_config_file, kill_daemon_and_verify
from ..test_constants import GITSTATUSD_PATH
from ..test_utils import run_cli_command

# real_temp_repo fixture now provided by conftest.py


@pytest.fixture
def real_env_with_existing_worktrees(real_temp_repo):
    """Set up environment with config file and create a couple existing worktrees."""
    # Kill any existing daemon first
    kill_daemon_and_verify(real_temp_repo)

    config_file = create_integration_test_config_file(real_temp_repo)

    # Use rationalized config system with ADGN_MAIN_REPO
    env = os.environ.copy()
    env["ADGN_MAIN_REPO"] = str(real_temp_repo.resolve())  # Ensure absolute path

    repo = pygit2.Repository(str(real_temp_repo))
    signature = pygit2.Signature("Test User", "test@example.com")

    # Create existing worktree 1
    worktree1_path = real_temp_repo / "worktrees" / "existing1"
    master_commit = repo.head.target
    branch1 = repo.create_branch("test/existing1", repo.get(master_commit))

    # Use git CLI for worktree creation since pygit2 doesn't support worktrees directly
    subprocess.run(
        ["git", "worktree", "add", str(worktree1_path), "test/existing1"],
        cwd=real_temp_repo,
        check=True,
    )

    # Add a file to existing worktree 1 using pygit2
    repo1 = pygit2.Repository(str(worktree1_path))
    (worktree1_path / "existing1.txt").write_text("Content from existing1")
    repo1.index.add("existing1.txt")
    repo1.index.write()
    tree1 = repo1.index.write_tree()
    repo1.create_commit(
        "HEAD", signature, signature, "Add existing1 content", tree1, [repo1.head.target]
    )

    # Create existing worktree 2
    worktree2_path = real_temp_repo / "worktrees" / "existing2"
    branch2 = repo.create_branch("test/existing2", repo.get(master_commit))
    subprocess.run(
        ["git", "worktree", "add", str(worktree2_path), "test/existing2"],
        cwd=real_temp_repo,
        check=True,
    )

    # Add a file to existing worktree 2 using pygit2
    repo2 = pygit2.Repository(str(worktree2_path))
    (worktree2_path / "existing2.txt").write_text("Content from existing2")
    repo2.index.add("existing2.txt")
    repo2.index.write()
    tree2 = repo2.index.write_tree()
    repo2.create_commit(
        "HEAD", signature, signature, "Add existing2 content", tree2, [repo2.head.target]
    )

    yield env, real_temp_repo

    # Cleanup: Kill daemon after test
    kill_daemon_and_verify(real_temp_repo)


# real_env fixture now provided by conftest.py


def test_real_workflow_with_existing_worktrees(real_env_with_existing_worktrees):
    """Test workflow starting with existing worktrees - tests real status display."""
    env, real_temp_repo = real_env_with_existing_worktrees

    try:
        # Step 1: Status should show existing worktrees
        result = run_cli_command(["sh"], env=env)
        print(
            f"Status with existing worktrees (exit={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
        assert result.returncode == 0
        assert "existing1" in result.stdout
        assert "existing2" in result.stdout

        # Step 2: Create a new worktree alongside existing ones
        result = run_cli_command(["sh", "-c", "new-feature"], env=env)
        print(f"Create new-feature (exit={result.returncode}):\n{result.stdout}\n{result.stderr}")
        assert result.returncode == 0

        # Verify new worktree created
        new_worktree_path = real_temp_repo / "worktrees" / "new-feature"
        assert new_worktree_path.exists()

        # Step 3: Status should now show all three worktrees
        result = run_cli_command(["sh"], env=env)
        print(
            f"Status with all worktrees (exit={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
        assert result.returncode == 0
        assert "existing1" in result.stdout
        assert "existing2" in result.stdout
        assert "new-feature" in result.stdout

        print("✅ Real workflow with existing worktrees test passed!")

    finally:
        # Cleanup is now handled by fixture teardown
        pass


def test_real_workflow_git_repo_to_worktrees_to_status(real_temp_repo, real_env):
    """
    Test workflow: git repo -> make worktrees 1,2 -> jump to worktree -> rm other -> status
    This tests the ACTUAL UNMODIFIED UNMOCKED program with real git operations.
    """

    try:
        # Step 1: Initial status (should show empty or main repo only)
        result = run_cli_command(["sh"], env=real_env)
        print(f"Initial status (exit={result.returncode}):\n{result.stdout}\n{result.stderr}")
        assert result.returncode == 0

        # Step 2: Create first worktree
        result = run_cli_command(["sh", "-c", "feature1"], env=real_env)
        print(f"Create feature1 (exit={result.returncode}):\n{result.stdout}\n{result.stderr}")
        assert result.returncode == 0

        # Verify worktree was actually created with real git
        worktree1_path = real_temp_repo / "worktrees" / "feature1"
        assert worktree1_path.exists(), f"Worktree 1 not created at {worktree1_path}"
        assert (worktree1_path / ".git").exists(), "Worktree 1 missing .git"

        # Verify git branch was created correctly using pygit2
        repo1 = pygit2.Repository(str(worktree1_path))
        current_branch = repo1.head.shorthand
        assert current_branch == "test/feature1", (
            f"Expected test/feature1 branch, got: {current_branch}"
        )

        # Step 3: Create second worktree
        result = run_cli_command(["sh", "-c", "feature2"], env=real_env)
        print(f"Create feature2 (exit={result.returncode}):\n{result.stdout}\n{result.stderr}")
        assert result.returncode == 0

        # Verify second worktree was created
        worktree2_path = real_temp_repo / "worktrees" / "feature2"
        assert worktree2_path.exists(), f"Worktree 2 not created at {worktree2_path}"

        # Step 4: Check status shows both worktrees
        result = run_cli_command(["sh"], env=real_env)
        print(
            f"Status with both worktrees (exit={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
        assert result.returncode == 0
        assert "feature1" in result.stdout
        assert "feature2" in result.stdout

        # Step 5: Navigate to feature1 (test cd command emission)
        result = run_cli_command(["sh", "feature1"], env=real_env)
        print(f"Navigate to feature1 (exit={result.returncode}):\n{result.stdout}\n{result.stderr}")
        assert result.returncode == 0
        # Note: cd command is emitted to fd3, we can't easily verify it here

        # Step 6: Test real git operations in the worktree
        test_file = worktree1_path / "test.txt"
        test_file.write_text("Hello from feature1!")

        # Add and commit in the worktree
        subprocess.run(["git", "add", "test.txt"], cwd=worktree1_path, check=True)
        subprocess.run(["git", "commit", "-m", "Add test file"], cwd=worktree1_path, check=True)

        # Step 7: Final status check should show the changes
        result = run_cli_command(["sh"], env=real_env)
        print(f"Final status (exit={result.returncode}):\n{result.stdout}\n{result.stderr}")
        assert result.returncode == 0

        print("✅ Real integration test passed!")

    finally:
        # Always clean up daemon
        # Cleanup is now handled by fixture teardown
        pass


def test_real_git_operations_in_worktrees(real_temp_repo, real_env):
    """Test that git operations work correctly in created worktrees."""

    try:
        # Debug: show what config the CLI is reading
        config_dir = real_temp_repo / ".config" / "adgn-wt"
        config_file = config_dir / "config.yaml"
        if config_file.exists():
            print(f"Config file contents:\n{config_file.read_text()}")
        else:
            print(f"Config file missing: {config_file}")

        # Create worktree
        result = run_cli_command(["sh", "-c", "git-test"], env=real_env)
        print(
            f"Create git-test worktree (exit={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
        assert result.returncode == 0

        worktree_path = real_temp_repo / "worktrees" / "git-test"
        print(f"Expected worktree path: {worktree_path}")
        print(f"Worktree path exists: {worktree_path.exists()}")

        # Debug: check what's actually in the worktrees directory
        worktrees_parent = real_temp_repo / "worktrees"
        if worktrees_parent.exists():
            print(f"Contents of worktrees dir: {list(worktrees_parent.iterdir())}")
        else:
            print(f"Worktrees dir doesn't exist: {worktrees_parent}")

        # Debug: check for the worktree in the parent directory too
        alt_path = real_temp_repo.parent / "worktrees" / "git-test"
        print(f"Alt path exists: {alt_path} -> {alt_path.exists()}")

        assert worktree_path.exists()

        # Test git operations in the worktree
        test_file = worktree_path / "test.txt"
        test_file.write_text("Hello from worktree!")

        # Add and commit
        subprocess.run(["git", "add", "test.txt"], cwd=worktree_path, check=True)
        subprocess.run(["git", "commit", "-m", "Test commit"], cwd=worktree_path, check=True)

        # Verify branch was created correctly
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=worktree_path, capture_output=True, text=True
        )
        assert "test/git-test" in result.stdout

        # Verify the file exists and has correct content
        assert test_file.exists()
        assert test_file.read_text() == "Hello from worktree!"

        # Verify commit was made
        result = subprocess.run(
            ["git", "log", "--oneline"], cwd=worktree_path, capture_output=True, text=True
        )
        assert "Test commit" in result.stdout

        print("✅ Real git operations test passed!")

    finally:
        # Cleanup is now handled by fixture teardown
        pass


def test_real_daemon_startup_and_kill(real_temp_repo, real_env):
    """Test that daemon actually starts and can be killed via CLI command."""

    try:
        # Step 1: Initial command should start the daemon
        result = run_cli_command(["sh"], env=real_env)
        print(
            f"Initial status (should start daemon) (exit={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
        assert result.returncode == 0

        # Step 2: Check that daemon files were created
        daemon_dir = real_temp_repo / ".wt"
        assert daemon_dir.exists(), "Daemon directory not created"

        pid_file = daemon_dir / "daemon.pid"
        socket_file = daemon_dir / "daemon.sock"

        # Give daemon a moment to start up
        time.sleep(0.5)

        # Step 3: Verify daemon is actually running
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            # Check if process exists
            try:
                os.kill(pid, 0)  # Signal 0 just checks if process exists
                print(f"✅ Daemon running with PID {pid}")
                daemon_was_running = True
            except OSError:
                print(f"❌ Daemon PID {pid} not found")
                daemon_was_running = False

            assert daemon_was_running, f"Daemon process {pid} not found"
        else:
            pytest.fail("Daemon PID file not created")

        # Step 4: Test kill-daemon command
        result = run_cli_command(["sh", "kill-daemon"], env=real_env)
        print(f"Kill daemon command (exit={result.returncode}):\n{result.stdout}\n{result.stderr}")
        assert result.returncode == 0

        # Step 5: Verify daemon is no longer running
        time.sleep(0.2)  # Brief wait for cleanup

        try:
            os.kill(pid, 0)  # Check if process still exists
            pytest.fail(f"Daemon process {pid} still running after kill command")
        except OSError:
            print(f"✅ Daemon process {pid} successfully killed")

        # Step 6: Verify cleanup happened
        # PID file should be removed or contain stale PID
        if pid_file.exists():
            new_pid = int(pid_file.read_text().strip())
            if new_pid == pid:
                pytest.fail("PID file not cleaned up after daemon kill")

        print("✅ Daemon startup and kill test passed!")

    finally:
        # Ensure cleanup even if test fails
        # Cleanup is now handled by fixture teardown
        pass
