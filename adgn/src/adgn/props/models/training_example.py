"""Training example model for ML training/evaluation.

A TrainingExample bundles a snapshot with its associated issues and false positives
for use in training/evaluation workflows.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from adgn.props.ids import SnapshotSlug
from adgn.props.models.issue import Issue, FalsePositive
from adgn.props.splits import Split


class TrainingExample(BaseModel):
    """A training/evaluation example: snapshot + issues + false positives.

    Designed for ML workflows where each example represents a complete
    evaluation unit with ground truth.
    """

    snapshot_slug: SnapshotSlug
    split: Split
    issues: list[Issue]
    false_positives: list[FalsePositive]

    model_config = ConfigDict(frozen=True)

    @property
    def target_files(self) -> set[Path]:
        """Files that have known ground truth (TP or FP issues)."""
        files: set[Path] = set()
        for issue in self.issues:
            for occ in issue.occurrences:
                files.update(occ.files.keys())
        for fp in self.false_positives:
            for occ in fp.occurrences:
                files.update(occ.files.keys())
        return files

    @property
    def issue_count(self) -> int:
        """Total number of true positive issues."""
        return len(self.issues)

    @property
    def false_positive_count(self) -> int:
        """Total number of false positives."""
        return len(self.false_positives)


__all__ = ["TrainingExample"]
