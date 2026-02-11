#!/usr/bin/env python3
"""Pre-commit hook to block changes to code/ in committed snapshots.

A snapshot is "committed" if its issues/ directory exists in HEAD.
Once committed, the code/ directory becomes immutable.
"""

import subprocess
import sys
from pathlib import Path

SPECIMENS_PREFIX = "props/specimens/"


def get_staged_files():
    """Get files staged for commit under props/specimens/."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], capture_output=True, text=True, check=True
    )
    return [f for f in result.stdout.strip().split("\n") if f and f.startswith(SPECIMENS_PREFIX)]


def is_in_committed_snapshot(file_path: str) -> bool:
    """Check if file is in code/ of a committed snapshot.

    Committed snapshots have an issues/ directory tracked in HEAD.
    Path structure: props/specimens/{repo}/{version}/code/...
    """
    path = Path(file_path)
    parts = path.parts

    if "code" not in parts:
        return False

    try:
        code_idx = parts.index("code")
        if code_idx < 2:
            return False

        snapshot_dir = Path(*parts[:code_idx])

        # Check if snapshot has an issues/ directory in HEAD
        issues_check = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{snapshot_dir}/issues"], check=False, capture_output=True
        )
        return issues_check.returncode == 0
    except (ValueError, IndexError):
        return False


def main():
    staged_files = get_staged_files()
    violations = [f for f in staged_files if is_in_committed_snapshot(f)]

    if violations:
        print("ERROR: Changes to code/ in committed snapshots are not allowed.", file=sys.stderr)
        print(file=sys.stderr)
        print("Committed snapshots are immutable. To modify:", file=sys.stderr)
        print("  1. Create a NEW snapshot with updated code", file=sys.stderr)
        print("  2. Or delete the snapshot and recapture", file=sys.stderr)
        print(file=sys.stderr)
        print("Blocked files:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
