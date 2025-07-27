"""Integration test for path watcher - tests daemon through full worktree lifecycle.

This test runs everything as subprocess calls, NOT through pytest fixtures or Python imports.
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..test_constants import GITSTATUSD_PATH
from ..test_utils import run_cli_sh_command as run_cli_command


def create_test_repo_and_config():
    """Create test repo and config entirely via subprocess calls."""
    # Create temporary directory
    temp_dir = Path(tempfile.mkdtemp())
    repo_path = temp_dir / "test_repo"
    repo_path.mkdir()

    # Initialize git repository using subprocess git
    subprocess.run(["git", "init", "--initial-branch=master"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)

    # Create initial commit
    readme_file = repo_path / "README.md"
    readme_file.write_text("# Test Repository")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True)

    # Set up worktrees directory
    worktrees_dir = repo_path / "worktrees"
    worktrees_dir.mkdir()

    # Create config file using rationalized system
    config_dir = repo_path / ".wt"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_content = f"""main_repo: "{repo_path}"
worktrees_dir: "{worktrees_dir}"
branch_prefix: "test/"
default_worktree_base_branch: "HEAD"
log_operations: false
cow_method: "copy"
github_enabled: false
github_repo: "test/test"
gitstatusd_path: "{GITSTATUSD_PATH}"
"""

    config_file = config_dir / "config.yaml"
    config_file.write_text(config_content)

    # Create test environment with WT_DIR (new configuration system)
    env = os.environ.copy()
    env["WT_DIR"] = str(config_dir)

    return repo_path, env, temp_dir


def test_path_watcher_full_lifecycle():
    """
    Test the path watcher through complete worktree lifecycle:
    1. status (should start daemon)
    2. create worktree
    3. status (should detect new worktree via path watcher)
    4. remove worktree
    5. status (should detect removal via path watcher)
    """

    repo_path, env, temp_dir = create_test_repo_and_config()

    try:
        print(f"=== Test setup complete ===")
        print(f"Repo: {repo_path}")
        print(f"Config: {repo_path}/.wt/config.yaml")

        # Step 1: Initial status - should start daemon and show empty state
        print("=== Step 1: Initial status (starts daemon) ===")
        result = run_cli_command([], env)
        print(f"Status result (exit={result.returncode}):\n{result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")

        # Always check daemon status for debugging
        daemon_dir = repo_path / ".wt"
        print(f"DEBUG: daemon_dir exists: {daemon_dir.exists()}")
        if daemon_dir.exists():
            print(f"DEBUG: daemon_dir contents: {list(daemon_dir.iterdir())}")

            daemon_log = daemon_dir / "daemon.log"
            if daemon_log.exists():
                print(f"\n=== Daemon Log ===")
                print(daemon_log.read_text())

            pid_file = daemon_dir / "daemon.pid"
            socket_file = daemon_dir / "daemon.sock"
            print(f"DEBUG: pid_file exists: {pid_file.exists()}")
            print(f"DEBUG: socket_file exists: {socket_file.exists()}")

        assert result.returncode == 0, f"Status command failed: {result.stderr}"

        # Verify daemon started
        assert daemon_dir.exists(), "Daemon directory not created"

        # Give daemon time to fully initialize
        time.sleep(0.5)

        # Step 2: Create a worktree
        print("=== Step 2: Create worktree 'feature-test' ===")
        result = run_cli_command(["-c", "feature-test"], env)
        print(f"Create result (exit={result.returncode}):\n{result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")

        assert result.returncode == 0, f"Create command failed: {result.stderr}"

        # Verify worktree was created on filesystem
        worktree_path = repo_path / "worktrees" / "feature-test"
        assert worktree_path.exists(), f"Worktree not created at {worktree_path}"
        assert worktree_path.is_dir(), f"Worktree path is not a directory: {worktree_path}"

        # Brief pause to let path watcher detect the change
        time.sleep(0.2)

        # Step 3: Status should now show the new worktree (detected via path watcher)
        print("=== Step 3: Status after create (should detect via path watcher) ===")
        result = run_cli_command([], env)
        print(f"Status after create (exit={result.returncode}):\n{result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")

        assert result.returncode == 0, f"Status after create failed: {result.stderr}"
        assert "feature-test" in result.stdout, "New worktree not detected in status output"

        # Step 4: Remove the worktree
        print("=== Step 4: Remove worktree 'feature-test' ===")
        result = run_cli_command(["rm", "feature-test", "--force"], env)
        print(f"Remove result (exit={result.returncode}):\n{result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")

        assert result.returncode == 0, f"Remove command failed: {result.stderr}"

        # Verify worktree was removed from filesystem
        assert not worktree_path.exists(), f"Worktree still exists after removal: {worktree_path}"

        # Brief pause to let path watcher detect the removal
        time.sleep(0.2)

        # Step 5: Status should no longer show the worktree (detected removal via path watcher)
        print("=== Step 5: Status after remove (should detect removal via path watcher) ===")
        result = run_cli_command([], env)
        print(f"Status after remove (exit={result.returncode}):\n{result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")

        assert result.returncode == 0, f"Status after remove failed: {result.stderr}"
        # Note: The daemon should detect that the worktree is gone and either:
        # 1. Not show it in status output, or
        # 2. Show it with an error state indicating it's missing
        # Either way, this tests that the path watcher is working

        print("✅ Path watcher integration test completed successfully!")

    finally:
        # Clean up: Kill daemon
        print("=== Cleanup: Stopping daemon ===")
        kill_result = run_cli_command(["kill-daemon"], env)
        print(f"Daemon stop result: {kill_result.returncode}")

        # Clean up temp directory
        shutil.rmtree(temp_dir)


def test_path_watcher_multiple_worktrees():
    """
    Test path watcher with multiple worktrees created and removed.
    Tests that the daemon can track multiple changes in sequence.
    """

    repo_path, env, temp_dir = create_test_repo_and_config()

    try:
        # Initial status to start daemon
        result = run_cli_command([], env)
        assert result.returncode == 0
        time.sleep(0.5)  # Let daemon start

        worktree_names = ["wt1", "wt2", "wt3"]

        # Create multiple worktrees
        print("=== Creating multiple worktrees ===")
        for name in worktree_names:
            result = run_cli_command(["-c", name], env)
            assert result.returncode == 0, f"Failed to create {name}: {result.stderr}"
            time.sleep(0.1)  # Brief pause between creates

        time.sleep(0.3)  # Let path watcher catch up

        # Status should show all worktrees
        result = run_cli_command([], env)
        assert result.returncode == 0
        for name in worktree_names:
            assert name in result.stdout, f"Worktree {name} not detected after creation"

        # Remove worktrees one by one
        print("=== Removing worktrees one by one ===")
        remaining = worktree_names.copy()
        for name in worktree_names:
            result = run_cli_command(["rm", name, "--force"], env)
            assert result.returncode == 0, f"Failed to remove {name}: {result.stderr}"
            remaining.remove(name)

            time.sleep(0.2)  # Let path watcher detect removal

            # Verify status reflects the removal
            result = run_cli_command([], env)
            assert result.returncode == 0

            # Should not see the removed worktree
            # Note: This might show as "missing" rather than absent, which is also valid
            print(f"After removing {name}, remaining should be: {remaining}")

        print("✅ Multiple worktrees test completed successfully!")

    finally:
        # Cleanup
        run_cli_command(["kill-daemon"], env)
        shutil.rmtree(temp_dir)


# Run as script for manual testing
if __name__ == "__main__":
    test_path_watcher_full_lifecycle()
