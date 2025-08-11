import os
from pathlib import Path

import pytest

from .conftest import kill_daemon_and_verify
from .test_utils import run_cli_sh_command




def test_copy_dirty_state_cli(real_env, real_temp_repo):
    env = real_env
    repo = real_temp_repo

    # Create source worktree via CLI
    src = "src_wt"
    result = run_cli_sh_command(["-c", src], env=env, timeout=20.0)
    assert result.returncode == 0, result.stderr
    src_path = Path(repo) / "worktrees" / src

    # Add untracked and modified files in source
    (src_path / "untracked.txt").write_text("hello")
    tracked = src_path / "README.md"
    tracked.write_text("base\n")
    # stage and commit in source worktree so file is tracked
    import subprocess
    subprocess.run(["git", "add", "README.md"], cwd=src_path, check=True)
    subprocess.run(["git", "commit", "-m", "add readme"], cwd=src_path, check=True)
    tracked.write_text("modified\n")

    # Create destination by copying from source
    dst = "dst_wt"
    result = run_cli_sh_command(["cp", src, dst], env=env, timeout=30.0)
    assert result.returncode == 0, result.stderr

    dst_path = Path(repo) / "worktrees" / dst
    assert dst_path.exists()
    # Untracked file should be present
    assert (dst_path / "untracked.txt").exists()
    # Tracked file modifications should be copied
    assert (dst_path / "README.md").read_text() == "modified\n"
