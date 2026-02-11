"""Centralized runs directory context and path derivation.

This module provides the single source of truth for all runs-related path construction.
No path tokens ("grader", "output.json", etc.) should be hardcoded outside this module.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from adgn.props.prop_utils import pkg_dir

# Path token constants - single source of truth
RUN_TYPE_CRITIC = "critic"
RUN_TYPE_GRADER = "grader"
INPUT_JSON = "input.json"
OUTPUT_JSON = "output.json"
EVENTS_JSONL = "events.jsonl"


def format_timestamp_session(dt: datetime | None = None) -> str:
    """Standard timestamp format for session/output directories: YYYYMMDD_HHMMSS.

    Args:
        dt: datetime to format (defaults to now)

    Returns:
        Formatted timestamp string (e.g., "20250127_153045")
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y%m%d_%H%M%S")


class RunsContext:
    """Context object for runs directory path derivation.

    Injected at CLI/entry point level. All path construction goes through this object.
    No code should independently compute runs paths or use hardcoded path tokens.
    """

    def __init__(self, base_dir: Path):
        """Initialize runs context.

        Args:
            base_dir: Base runs directory (e.g., pkg_dir() / "runs")
        """
        self.base_dir = base_dir

    @classmethod
    def from_pkg_dir(cls) -> RunsContext:
        """Create RunsContext from package directory (default location).

        Returns:
            RunsContext for pkg_dir() / "runs"
        """
        return cls(pkg_dir() / "runs")

    def issue_eval_dir(self, identifier: str, timestamp: str | None = None) -> Path:
        """Get output directory for issue evaluation runs (lint_issue harness).

        Args:
            identifier: Identifier for the eval (e.g., specimen_issue_id or "all")
            timestamp: Optional timestamp string (defaults to creating new one)

        Returns:
            Path to eval output directory (created if it doesn't exist)
            Structure: runs/evals/{identifier}_{timestamp}/
        """
        if timestamp is None:
            timestamp = format_timestamp_session()
        path = self.base_dir / "evals" / f"{identifier}_{timestamp}"
        path.mkdir(parents=True, exist_ok=True)
        return path
