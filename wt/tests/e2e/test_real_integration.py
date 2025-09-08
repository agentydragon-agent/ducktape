"""Real integration tests for actual CLI."""

import os
import time
from pathlib import Path

import pytest

from wt.shared.git_utils import git_run

from ..test_utils import run_cli_command

pytestmark = pytest.mark.timeout(10)


def test_real_program_workflow(real_temp_repo, real_env):
    # Initial status
    result = run_cli_command(["sh"], env=real_env, timeout=10.0)
    assert result.returncode == 0

    # Create first worktree
    result = run_cli_command(["sh", "-c", "feature1"], env=real_env, timeout=10.0)
    assert result.returncode == 0
    worktree1_path = real_temp_repo / "worktrees" / "feature1"
    assert worktree1_path.exists()
    assert (worktree1_path / ".git").exists()

    # Create second worktree
    result = run_cli_command(["sh", "-c", "feature2"], env=real_env, timeout=10.0)
    assert result.returncode == 0
    worktree2_path = real_temp_repo / "worktrees" / "feature2"
    assert worktree2_path.exists()

    # Status shows both
    result = run_cli_command(["sh"], env=real_env, timeout=10.0)
    assert result.returncode == 0
    assert "feature1" in result.stdout
    assert "feature2" in result.stdout

    # Navigate to feature1
    result = run_cli_command(["sh", "feature1"], env=real_env, timeout=10.0)
    assert result.returncode == 0

    # Remove feature2
    result = run_cli_command(
        ["sh", "rm", "feature2", "--force"],
        env=real_env,
        cwd=worktree1_path,
        timeout=10.0,
    )
    assert result.returncode == 0
    git_list = git_run(["worktree", "list"], cwd=real_temp_repo)
    assert str(worktree2_path) not in git_list.stdout.decode()

    # Final status
    result = run_cli_command(["sh"], env=real_env, timeout=10.0)
    assert result.returncode == 0


def test_real_daemon_startup_and_communication(real_temp_repo, real_env):
    # Start daemon
    result = run_cli_command(["sh"], env=real_env, timeout=10.0)
    assert result.returncode == 0

    daemon_dir = Path(real_env["WT_DIR"]).resolve()
    assert daemon_dir.exists()
    pid_file = daemon_dir / "daemon.pid"

    time.sleep(0.5)
    assert pid_file.exists()
    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, 0)
    except OSError:
        pytest.fail(f"Daemon PID {pid} not found")


def test_real_git_operations(real_temp_repo, real_env):
    # Create worktree
    result = run_cli_command(["sh", "-c", "git-test"], env=real_env, timeout=10.0)
    assert result.returncode == 0

    worktree_path = real_temp_repo / "worktrees" / "git-test"
    assert worktree_path.exists()

    # Perform git operations
    (worktree_path / "test.txt").write_text("Hello from worktree!")
    git_run(["add", "test.txt"], cwd=worktree_path)
    git_run(["commit", "-m", "Test commit"], cwd=worktree_path)

    # Verify branch name
    result = git_run(
        ["branch", "--show-current"], cwd=worktree_path, capture_output=True
    )
    assert "test/git-test" in result.stdout.decode()
