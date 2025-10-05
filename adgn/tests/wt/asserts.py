"""Shared assertions and parsing helpers for WT CLI output tests."""

from __future__ import annotations

import re
from typing import Dict


def extract_status_rows(output: str) -> Dict[str, str]:
    """Parse status output into a mapping of worktree name -> full line.

    Filters out spinner/header lines and reduces access to rows by name.
    """
    lines = [ln for ln in output.splitlines() if ln and not ln.startswith(("✓", "⟳"))]
    rows: Dict[str, str] = {}
    for ln in lines:
        name = ln.split(maxsplit=1)[0]
        rows[name] = ln
    return rows


def status_row_ok(
    line: str,
    *,
    must_contain: list[str] | None = None,
    commit_re: str = r"[0-9a-f]{8}\b",
) -> bool:
    """Validate a status row has an 8-hex commit and required substrings."""
    must = must_contain or ["clean", " running"]
    # name, spaces, 8-hex commit, spaces, rest
    if not re.match(rf"^[^\s]+\s+{commit_re}", line):
        return False
    return all(part in line for part in must)
