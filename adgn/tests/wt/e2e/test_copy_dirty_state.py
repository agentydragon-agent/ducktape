from datetime import timedelta
from pathlib import Path
import subprocess


def test_copy_dirty_state_cli(wt_cli, real_temp_repo):
    # Create source worktree via CLI
    src = "src_wt"
    result = wt_cli.sh_c(src, timeout=timedelta(seconds=20.0))
    assert result.returncode == 0, result.stderr
    src_path = Path(real_temp_repo) / "worktrees" / src

    # Add untracked and modified files in source
    (src_path / "untracked.txt").write_text("hello")
    tracked = src_path / "README.md"
    tracked.write_text("base\n")
    # stage and commit in source worktree so file is tracked

    subprocess.run(["git", "add", "README.md"], cwd=src_path, check=True)
    subprocess.run(["git", "commit", "-m", "add readme"], cwd=src_path, check=True)
    tracked.write_text("modified\n")

    # Create destination by copying from source
    dst = "dst_wt"
    result = wt_cli.sh("cp", src, dst, timeout=timedelta(seconds=30.0))
    assert result.returncode == 0, result.stderr

    dst_path = Path(real_temp_repo) / "worktrees" / dst
    assert dst_path.exists()
    # Untracked file should be present
    assert (dst_path / "untracked.txt").exists()
    # Tracked file modifications should be copied
    assert (dst_path / "README.md").read_text() == "modified\n"
