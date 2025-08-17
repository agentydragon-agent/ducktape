import shutil

import pytest

from ..conftest import kill_daemon_and_verify
from ..test_utils import run_cli_command

pytestmark = pytest.mark.integration


def test_manual_delete_of_old_worktree_does_not_break_new_create(
    real_temp_repo,
    real_env,
):
    """
    Repro for server crash when a previously-registered worktree directory was
    deleted out-of-band. Creating a new worktree should not fail with
    "Repository not found at <stale path>".
    """
    # Ensure clean daemon state
    kill_daemon_and_verify(real_temp_repo)

    # 1) Create an initial worktree
    name_old = "stale-old"
    r1 = run_cli_command(["sh", "-c", name_old], env=real_env, timeout=20.0)
    assert r1.returncode == 0, f"Initial create failed: {r1.stderr}"

    wt_old = real_temp_repo / "worktrees" / name_old
    assert wt_old.exists()

    # 2) Manually delete the directory (simulate out-of-band removal)
    shutil.rmtree(wt_old, ignore_errors=True)
    assert not wt_old.exists()

    # 3) Create a new worktree; previously this crashed on list_worktrees()
    name_new = "after-stale"
    r2 = run_cli_command(["sh", "-c", name_new], env=real_env, timeout=20.0)
    assert r2.returncode == 0, (
        f"New worktree creation failed (likely due to stale entry crash):\nstdout=\n{r2.stdout}\nstderr=\n{r2.stderr}"
    )

    wt_new = real_temp_repo / "worktrees" / name_new
    assert wt_new.exists(), f"New worktree not created at {wt_new}"

    # Optional: a quick status call should succeed and not mention errors
    r3 = run_cli_command(["sh"], env=real_env, timeout=20.0)
    assert r3.returncode == 0
