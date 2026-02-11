"""Training example model for ML training/evaluation.

A TrainingExample represents a focused code review scenario: given a snapshot and
a set of targeted files, which true positives are catchable and which false positives
are relevant?
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from adgn.props.ids import SnapshotSlug
from adgn.props.models.true_positive import FalsePositive, TruePositive
from adgn.props.splits import Split


class TrainingExample(BaseModel):
    """A focused training example: snapshot + targeted files + catchable ground truth.

    Represents asking a critic: "Review these specific files in this snapshot,
    find the issues you can detect."

    Derived from:
        - snapshot_slug: which codebase snapshot
        - targeted_files: which files we're asking the critic to review

    Computed outputs:
        - true_positives: TPs where ∃ minimal_trigger_set ⊆ targeted_files
        - false_positives: FPs whose relevant_files overlap targeted_files (TODO)
    """

    snapshot_slug: SnapshotSlug
    split: Split
    targeted_files: frozenset[Path] = Field(description="Files to review in this training example (INPUT)")

    # Computed/filtered outputs
    true_positives: list[TruePositive] = Field(description="Catchable true positives given targeted_files")
    false_positives: list[FalsePositive] = Field(description="Relevant false positives given targeted_files")

    model_config = ConfigDict(frozen=True)

    @staticmethod
    def should_include_tp(tp: TruePositive, targeted_files: set[Path]) -> bool:
        """Check if a true positive is catchable given targeted files.

        Returns True if ANY occurrence has at least one minimal triggering set
        that is a non-strict subset of targeted_files.

        Args:
            tp: True positive to check
            targeted_files: Files being reviewed

        Returns:
            True if the TP is catchable with the given files
        """
        for occurrence in tp.occurrences:
            for trigger_set in occurrence.expect_caught_from:
                # trigger_set is a frozenset[Path]
                # Check if trigger_set ⊆ targeted_files (non-strict subset)
                if trigger_set <= targeted_files:
                    return True
        return False

    @staticmethod
    def should_include_fp(fp: FalsePositive, targeted_files: set[Path]) -> bool:
        """Check if a false positive is relevant given targeted files.

        Currently always returns True (includes all FPs from snapshot).

        TODO: Implement proper filtering - check if relevant_files overlap with targeted_files
        for any occurrence: any(bool(occ.relevant_files & targeted_files) for occ in fp.occurrences)

        Args:
            fp: False positive to check
            targeted_files: Files being reviewed (currently unused)

        Returns:
            True (always includes all FPs for now)
        """
        # For now: always include all FPs
        return True


__all__ = ["TrainingExample"]
