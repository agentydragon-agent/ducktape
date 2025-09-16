import time

import pytest

from adgn.wt.shared.git_utils import git_run

from ..test_utils import run_cli_command

pytestmark = pytest.mark.timeout(20)


@pytest.mark.integration
def test_worktree_add_then_remove_reflected_in_status(real_env, real_temp_repo):
    # Initially, status should show no worktrees
    r0 = run_cli_command(["sh"], env=real_env, timeout=10.0)
    assert r0.returncode == 0

    # Create a worktree via CLI
    name = "dyn-x"
    r1 = run_cli_command(["sh", "-c", name], env=real_env, timeout=10.0)
    assert r1.returncode == 0

    # Poll until it appears
    deadline = time.time() + 10
    appeared = False
    while time.time() < deadline:
        r = run_cli_command(["sh"], env=real_env, timeout=10.0)
        if name in r.stdout:
            appeared = True
            break
        time.sleep(0.2)
    assert appeared, "newly created worktree did not appear in status output"

    # Remove the worktree via CLI
    r2 = run_cli_command(["sh", "rm", name, "--force"], env=real_env, timeout=15.0)
    assert r2.returncode == 0

    # Ensure git no longer lists the worktree (verifies git worktree remove)

    git_list = git_run(["worktree", "list"], cwd=real_temp_repo)
    assert str(real_temp_repo / "worktrees" / name) not in git_list.stdout.decode(), (
        "Worktree still listed in main repo after removal"
    )

    # Poll until it disappears
    deadline = time.time() + 10
    gone = False
    while time.time() < deadline:
        r = run_cli_command(["sh"], env=real_env, timeout=10.0)
        if name not in r.stdout:
            gone = True
            break
        time.sleep(0.2)
    assert gone, "deleted worktree still present in status output"
