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

    def discover_grader_runs(self) -> list[Path]:
        """Find all grader run directories.

        Returns:
            List of run directories (each containing input.json and output.json)
        """
        # Pattern: runs/*/grader/*/*/output.json
        output_files = sorted(self.base_dir.rglob(f"*/{RUN_TYPE_GRADER}/*/*/{OUTPUT_JSON}"))
        return [f.parent for f in output_files]

    def discover_critic_runs(self) -> list[Path]:
        """Find all critic run directories.

        Returns:
            List of run directories (each containing input.json and output.json)
        """
        # Pattern: runs/*/critic/*/*/output.json
        output_files = sorted(self.base_dir.rglob(f"*/{RUN_TYPE_CRITIC}/*/*/{OUTPUT_JSON}"))
        return [f.parent for f in output_files]

    def run_input_path(self, run_dir: Path) -> Path:
        """Get input.json path for a run directory.

        Args:
            run_dir: Run directory

        Returns:
            Path to input.json
        """
        return run_dir / INPUT_JSON

    def run_output_path(self, run_dir: Path) -> Path:
        """Get output.json path for a run directory.

        Args:
            run_dir: Run directory

        Returns:
            Path to output.json
        """
        return run_dir / OUTPUT_JSON

    def run_events_path(self, run_dir: Path) -> Path:
        """Get events.jsonl path for a run directory.

        Args:
            run_dir: Run directory

        Returns:
            Path to events.jsonl (agent transcript)
        """
        return run_dir / EVENTS_JSONL

    def cluster_output_dir(self, timestamp: str | None = None) -> Path:
        """Get output directory for clustering runs.

        Args:
            timestamp: Optional timestamp string (defaults to creating new one)

        Returns:
            Path to cluster output directory
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.base_dir / "cluster" / timestamp

    def prompt_optimize_output_dir(self, timestamp: str | None = None) -> Path:
        """Get output directory for prompt optimization runs.

        Args:
            timestamp: Optional timestamp string (defaults to creating new one)

        Returns:
            Path to prompt optimization output directory
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.base_dir / f"prompt_optimize_{timestamp}"

    def prompt_evals_dir(self) -> Path:
        """Get shared directory for prompt evaluations.

        Returns:
            Path to prompt_evals directory
        """
        return self.base_dir / "prompt_evals"
