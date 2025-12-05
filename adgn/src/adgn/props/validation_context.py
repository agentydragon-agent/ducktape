"""Validation contexts for typed IDs and paths.

Provides contexts that enable strict validation of typed IDs and paths:
- SpecimenContext: for specimen-derived data (files, TP/FP IDs)
- GradedCritiqueContext: for critique-derived IDs (input IDs during grading)

Key design:
- Contexts store frozenset[BaseIssueID] (validated base IDs)
- Validators compare .id field against context's base ID sets
- Strict validation: validators use info.context["key"] directly (KeyError if missing)
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.paths import FileType, classify_path


class SpecimenContext:
    """Validation context for specimen-derived data.

    Contains file system information and allowed issue IDs from a hydrated specimen.
    Used by:
    - SpecimenRelativePath (validate file existence and type)
    - TruePositiveID (validates .id against allowed_tp_ids)
    - FalsePositiveID (validates .id against allowed_fp_ids)

    Context key: "snapshots"

    TODO: Rename class to SnapshotContext when unbundling specimen concept.
    """

    def __init__(
        self,
        snapshot_slug: SnapshotSlug,
        all_discovered_files: dict[Path, FileType],
        allowed_tp_ids: Iterable[BaseIssueID],
        allowed_fp_ids: Iterable[BaseIssueID],
    ):
        self.snapshot_slug = snapshot_slug
        self.all_discovered_files = all_discovered_files
        self.allowed_tp_ids: frozenset[BaseIssueID] = frozenset(allowed_tp_ids)
        self.allowed_fp_ids: frozenset[BaseIssueID] = frozenset(allowed_fp_ids)

    @classmethod
    def from_hydrated_specimen(
        cls,
        snapshot_slug: SnapshotSlug,
        hydrated_root: Path,
        specimen_issues: Iterable[BaseIssueID],
        specimen_fps: Iterable[BaseIssueID],
    ) -> SpecimenContext:
        """Build file map from hydrated_root via rglob("*") and classify_path.

        TODO: Rename to from_hydrated_snapshot when unbundling specimen concept.
        """
        all_discovered_files = {p.relative_to(hydrated_root): classify_path(p) for p in hydrated_root.rglob("*")}

        return cls(
            snapshot_slug=snapshot_slug,
            all_discovered_files=all_discovered_files,
            allowed_tp_ids=specimen_issues,
            allowed_fp_ids=specimen_fps,
        )


class GradedCritiqueContext:
    """Validation context for critique-derived IDs (used only during grading).

    Contains allowed input IDs from the critique being graded.
    Used by InputIssueID validators.

    Context key: "graded_critique_context"
    """

    def __init__(self, allowed_input_ids: Iterable[BaseIssueID]):
        self.allowed_input_ids: frozenset[BaseIssueID] = frozenset(allowed_input_ids)
