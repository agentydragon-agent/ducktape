"""E2E test: create multiple worktrees and verify `wt status` output.

Uses the real CLI via subprocess with completely isolated WT_DIR per test
through the existing `real_env` fixture and helpers.
"""

from datetime import timedelta
from pathlib import Path
import time

from hamcrest import assert_that, contains_string
import pytest

from tests.wt.asserts import extract_status_rows, status_row_ok

from ..test_utils import run_cli_command

pytestmark = pytest.mark.timeout(10)


@pytest.mark.integration
def test_status_lists_multiple_worktrees(real_temp_repo, real_env):
    """Create two worktrees and ensure `wt sh` status output reflects them."""

    # Initial status should succeed; header should include component summary
    result = run_cli_command([], env=real_env, timeout=timedelta(seconds=10.0))
    assert result.returncode == 0
    assert_that(result.stdout, contains_string("gitstatusd"))

    # Create first worktree
    result = run_cli_command(
        ["create", "--yes", "alpha"], env=real_env, timeout=timedelta(seconds=10.0)
    )
    assert result.returncode == 0

    # Verify created on disk
    wt1 = Path(real_temp_repo) / "worktrees" / "alpha"
    assert wt1.exists()
    assert (wt1 / ".git").exists()

    # Create second worktree
    result = run_cli_command(
        ["create", "--yes", "beta"], env=real_env, timeout=timedelta(seconds=10.0)
    )
    assert result.returncode == 0

    wt2 = Path(real_temp_repo) / "worktrees" / "beta"
    assert wt2.exists()
    assert (wt2 / ".git").exists()

    # Poll until both worktrees are reported as clean and running, and commit column is hex
    deadline = time.time() + 5.0
    last_out = ""
    while time.time() < deadline:
        result = run_cli_command([], env=real_env, timeout=timedelta(seconds=3.0))
        assert result.returncode == 0
        last_out = result.stdout
        rows = extract_status_rows(last_out)
        l1 = rows.get("alpha")
        l2 = rows.get("beta")
        if l1 and l2 and status_row_ok(l1) and status_row_ok(l2):
            break
        time.sleep(0.2)
    else:
        raise AssertionError(
            f"Status did not reach clean/running with hex commit for both worktrees.\nLast output:\n{last_out}",
        )
