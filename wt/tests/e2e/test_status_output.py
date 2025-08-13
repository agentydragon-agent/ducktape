"""E2E test: create multiple worktrees and verify `wt status` output.

Uses the real CLI via subprocess with completely isolated WT_DIR per test
through the existing `real_env` fixture and helpers.
"""

import time
from pathlib import Path

import pytest

from ..test_utils import run_cli_command

pytestmark = pytest.mark.timeout(10)


@pytest.mark.integration
def test_status_lists_multiple_worktrees(real_temp_repo, real_env):
    """Create two worktrees and ensure `wt sh` status output reflects them."""

    # Initial status should succeed; header should include component summary
    result = run_cli_command(["sh"], env=real_env, timeout=10.0)
    assert result.returncode == 0
    assert "gitstatusd" in result.stdout

    # Create first worktree
    result = run_cli_command(["sh", "-c", "alpha"], env=real_env, timeout=10.0)
    assert result.returncode == 0

    # Verify created on disk
    wt1 = Path(real_temp_repo) / "worktrees" / "alpha"
    assert wt1.exists() and (wt1 / ".git").exists()

    # Create second worktree
    result = run_cli_command(["sh", "-c", "beta"], env=real_env, timeout=10.0)
    assert result.returncode == 0

    wt2 = Path(real_temp_repo) / "worktrees" / "beta"
    assert wt2.exists() and (wt2 / ".git").exists()

    # Poll until both worktrees are reported as clean and running, and commit column is hex
    deadline = time.time() + 5.0
    last_out = ""
    while time.time() < deadline:
        result = run_cli_command(["sh"], env=real_env, timeout=10.0)
        assert result.returncode == 0
        out = result.stdout
        last_out = out
        # Find lines for each worktree
        lines = [ln for ln in out.splitlines() if ln and not ln.startswith(("✓", "⟳"))]
        def line_for(name: str) -> str | None:
            prefix = f"{name} "
            for ln in lines:
                if ln.startswith(prefix):
                    return ln
            return None
        l1 = line_for("alpha")
        l2 = line_for("beta")
        def commit_ok(line: str) -> bool:
            import re
            # Full-line regex: name, spaces, 8-hex, spaces, rest
            return re.match(r"^[a-zA-Z0-9._/-]+\s+[0-9a-f]{8}\b", line) is not None
        if (
            l1 and l2 and ("clean" in l1) and (" running" in l1) and ("clean" in l2) and (" running" in l2)
            and commit_ok(l1) and commit_ok(l2)
        ):
            break
        time.sleep(0.2)
    else:
        raise AssertionError(f"Status did not reach clean/running with hex commit for both worktrees.\nLast output:\n{last_out}")
