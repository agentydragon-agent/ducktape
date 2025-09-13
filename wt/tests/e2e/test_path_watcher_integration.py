"""Integration test for path watcher - tests daemon through full worktree lifecycle.

This test runs everything as subprocess calls, NOT through pytest fixtures or Python imports.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from wt.shared.git_utils import git_run

from ..test_data import (
    WATCHER_DEBOUNCE_SECS as DEBOUNCE_SECS,  # keep in sync with test config
)
from ..test_utils import run_cli_sh_command as run_cli_command


def _status(env) -> str:
    r = run_cli_command([], env, timeout=5.0)
    assert r.returncode == 0, r.stderr
    return r.stdout


def wait_for_status_contains(
    env,
    needle: str,
    timeout: float = DEBOUNCE_SECS * 8,
) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = _status(env)
        if needle in last:
            return
        time.sleep(DEBOUNCE_SECS)
    pytest.fail(
        f"Timed out waiting for status to contain '{needle}'. Last output:\n{last}",
    )


def wait_for_status_contains_all(
    env,
    needles: list[str],
    timeout: float = DEBOUNCE_SECS * 8,
) -> None:
    deadline = time.time() + timeout
    last = ""
    needles = list(needles)
    while time.time() < deadline:
        last = _status(env)
        if all(n in last for n in needles):
            return
        time.sleep(DEBOUNCE_SECS)
    missing = [n for n in needles if n not in last]
    pytest.fail(
        f"Timed out waiting for status to contain all {needles}. Missing: {missing}. Last output:\n{last}",
    )


def wait_for_status_not_contains(
    env,
    needle: str,
    timeout: float = DEBOUNCE_SECS * 8,
) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = _status(env)
        if needle not in last:
            return
        time.sleep(DEBOUNCE_SECS)
    pytest.fail(
        f"Timed out waiting for status to drop '{needle}'. Last output:\n{last}",
    )


def create_test_repo_and_config():
    """Create test repo and config entirely via subprocess calls."""
    # Create temporary directory
    temp_dir = Path(tempfile.mkdtemp())
    repo_path = temp_dir / "test_repo"
    repo_path.mkdir()

    # Initialize git repository using subprocess git
    git_run(["init", "--initial-branch=master"], cwd=repo_path)
    git_run(["config", "user.name", "Test User"], cwd=repo_path)
    git_run(["config", "user.email", "test@example.com"], cwd=repo_path)

    # Create initial commit
    readme_file = repo_path / "README.md"
    readme_file.write_text("# Test Repository")
    git_run(["add", "README.md"], cwd=repo_path)
    git_run(["commit", "-m", "Initial commit"], cwd=repo_path)

    # Set up worktrees directory
    worktrees_dir = repo_path / "worktrees"
    worktrees_dir.mkdir()

    # Create config file using rationalized system
    config_dir = repo_path / ".wt"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_content = f"""main_repo: "{repo_path}"
worktrees_dir: "{worktrees_dir}"
branch_prefix: "test/"
upstream_branch: "HEAD"
log_operations: false
cow_method: "copy"
github_enabled: false
github_repo: "test/test"
git_watcher_debounce_delay: {DEBOUNCE_SECS}
"""

    config_file = config_dir / "config.yaml"
    config_file.write_text(config_content)

    # Create test environment with WT_DIR and PYTHONPATH for -m wt.cli
    env = os.environ.copy()
    env["WT_DIR"] = str(config_dir)
    # Ensure -m wt.cli importable
    # Now handled by session autouse fixture in conftest.py

    return repo_path, env, temp_dir


@pytest.mark.timeout(30)
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
        print("=== Test setup complete ===")
        print(f"Repo: {repo_path}")
        print(f"Config: {repo_path}/.wt/config.yaml")

        # Step 1: Initial status - should start daemon and show empty state
        print("=== Step 1: Initial status (starts daemon) ===")
        result = run_cli_command([], env, timeout=5.0)
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
                print("\n=== Daemon Log ===")
                print(daemon_log.read_text())

            pid_file = daemon_dir / "daemon.pid"
            socket_file = daemon_dir / "daemon.sock"
            print(f"DEBUG: pid_file exists: {pid_file.exists()}")
            print(f"DEBUG: socket_file exists: {socket_file.exists()}")

        assert result.returncode == 0, f"Status command failed: {result.stderr}"

        # Verify daemon started
        assert daemon_dir.exists(), "Daemon directory not created"

        # No sleep needed: CLI returns after daemon handshake is complete

        # Step 2: Create a worktree
        print("=== Step 2: Create worktree 'feature-test' ===")
        result = run_cli_command(["-c", "feature-test"], env, timeout=5.0)
        print(f"Create result (exit={result.returncode}):\n{result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")

        assert result.returncode == 0, f"Create command failed: {result.stderr}"

        # Verify worktree was created on filesystem
        worktree_path = repo_path / "worktrees" / "feature-test"
        assert worktree_path.exists(), f"Worktree not created at {worktree_path}"
        assert worktree_path.is_dir(), (
            f"Worktree path is not a directory: {worktree_path}"
        )

        # Wait for watcher-driven status to reflect the new worktree
        wait_for_status_contains(env, "feature-test")

        # Step 3: Status should now show the new worktree (detected via path watcher)
        print("=== Step 3: Status after create (should detect via path watcher) ===")
        result = run_cli_command([], env, timeout=5.0)
        print(f"Status after create (exit={result.returncode}):\n{result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")

        assert result.returncode == 0, f"Status after create failed: {result.stderr}"
        assert "feature-test" in result.stdout, (
            "New worktree not detected in status output"
        )

        # Step 4: Remove the worktree
        print("=== Step 4: Remove worktree 'feature-test' ===")
        result = run_cli_command(["rm", "feature-test", "--force"], env, timeout=5.0)
        print(f"Remove result (exit={result.returncode}):\n{result.stdout}")
        if result.stderr:
            print(f"STDERR: {result.stderr}")

        assert result.returncode == 0, f"Remove command failed: {result.stderr}"
        # Ensure git no longer lists the worktree (verifies git worktree remove succeeded)
        git_list = git_run(["worktree", "list"], cwd=repo_path)
        assert str(worktree_path) not in git_list.stdout.decode(), (
            "Worktree still listed in main repo after removal"
        )

        # Verify worktree was removed from filesystem
        assert not worktree_path.exists(), (
            f"Worktree still exists after removal: {worktree_path}"
        )

        # Wait for watcher to drop the worktree from status
        wait_for_status_not_contains(env, "feature-test")

        # Step 5: Status should no longer show the worktree (detected removal via path watcher)
        print(
            "=== Step 5: Status after remove (should detect removal via path watcher) ===",
        )
        result = run_cli_command([], env, timeout=5.0)
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
        kill_result = run_cli_command(["kill-daemon"], env, timeout=5.0)
        print(f"Daemon stop result: {kill_result.returncode}")

        # Clean up temp directory
        shutil.rmtree(temp_dir)


@pytest.mark.timeout(30)
def test_path_watcher_multiple_worktrees():
    """
    Test path watcher with multiple worktrees created and removed.
    Tests that the daemon can track multiple changes in sequence.
    """

    repo_path, env, temp_dir = create_test_repo_and_config()

    try:
        # Initial status to start daemon
        result = run_cli_command([], env, timeout=5.0)
        assert result.returncode == 0
        # No sleep needed: CLI returns after daemon handshake is complete

        worktree_names = ["wt1", "wt2", "wt3"]

        # Create multiple worktrees
        print("=== Creating multiple worktrees ===")
        for name in worktree_names:
            result = run_cli_command(["-c", name], env, timeout=5.0)
            assert result.returncode == 0, f"Failed to create {name}: {result.stderr}"
            time.sleep(0.1)  # Brief pause between creates

        # Wait for all worktrees to appear in status in one poll loop
        wait_for_status_contains_all(env, worktree_names)

        # Status should show all worktrees
        result = run_cli_command([], env, timeout=5.0)
        assert result.returncode == 0
        for name in worktree_names:
            assert name in result.stdout, f"Worktree {name} not detected after creation"

        # Remove worktrees one by one
        print("=== Removing worktrees one by one ===")
        remaining = worktree_names.copy()

        def _wait_until_removed(env, missing_name: str, timeout: float = 6.0):
            deadline = time.time() + timeout
            last = ""
            while time.time() < deadline:
                r = run_cli_command([], env, timeout=3.0)
                if r.returncode == 0:
                    last = r.stdout
                    if missing_name not in last:
                        return True
                time.sleep(DEBOUNCE_SECS)
            print(f"DEBUG last status while waiting removal of {missing_name}:\n{last}")
            return False

        for name in worktree_names:
            result = run_cli_command(["rm", name, "--force"], env, timeout=5.0)
            assert result.returncode == 0, f"Failed to remove {name}: {result.stderr}"
            # Verify git no longer lists the worktree entry
            wt_path = repo_path / "worktrees" / name
            git_list = git_run(["worktree", "list"], cwd=repo_path)
            assert str(wt_path) not in git_list.stdout.decode(), (
                f"Worktree {name} still listed in main repo after removal"
            )
            remaining.remove(name)

            assert _wait_until_removed(env, name), (
                f"Worktree {name} still present in status after removal"
            )
            print(f"After removing {name}, remaining should be: {remaining}")

        print("✅ Multiple worktrees test completed successfully!")

    finally:
        # Cleanup
        run_cli_command(["kill-daemon"], env)
        shutil.rmtree(temp_dir)


# Run as script for manual testing
if __name__ == "__main__":
    test_path_watcher_full_lifecycle()
