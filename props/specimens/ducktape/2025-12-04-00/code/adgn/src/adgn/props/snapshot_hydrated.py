"""Hydrated snapshot - single object containing record + content root."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING

from adgn.props.ids import FalsePositiveID, TruePositiveID
from adgn.props.models.snapshot import SnapshotDoc
from adgn.props.paths import FileType

if TYPE_CHECKING:
    from adgn.props.snapshot_registry import KnownFalsePositive, SnapshotRecord, TruePositiveIssue


@dataclass
class HydratedSnapshot:
    """Single object containing snapshot record + hydrated content root.

    Replaces awkward tuple unpacking from load_and_hydrate().
    Provides convenient access to snapshot data and the hydrated working tree.

    Example:
        registry = SnapshotRegistry()
        async with registry.load_and_hydrate("ducktape/2025-11-20") as hydrated:
            # Access snapshot data
            files = hydrated.all_discovered_files
            issues = hydrated.issues

            # Access hydrated content
            wiring = properties_docker_spec(hydrated.content_root, ...)
    """

    record: SnapshotRecord
    content_root: Path

    # Convenience properties (delegate to record)
    @property
    def manifest(self) -> SnapshotDoc:
        """Snapshot manifest (source, bundle)."""
        return self.record.manifest

    @property
    def all_discovered_files(self) -> dict[Path, FileType]:
        """All files discovered during hydration (includes files without ground truth issues)."""
        return self.record.all_discovered_files

    @property
    def slug(self) -> str:
        """Snapshot slug (e.g., 'ducktape/2025-11-20')."""
        return self.record.slug

    @property
    def true_positives(self) -> dict[TruePositiveID, TruePositiveIssue]:
        """True positive issues (canonical ground truth)."""
        return self.record.true_positives

    @property
    def false_positives(self) -> dict[FalsePositiveID, KnownFalsePositive]:
        """Known false positives."""
        return self.record.false_positives

    def files_with_issues(self) -> set[Path]:
        """Return files that have known ground truth TP or FP issues.

        Returns:
            Set of relative paths mentioned in issues or false_positives.
        """
        tp_files = (
            occurrence.files.keys()
            for issue_record in self.true_positives.values()
            for occurrence in issue_record.occurrences
        )
        fp_files = (
            occurrence.files.keys()
            for issue_record in self.false_positives.values()
            for occurrence in issue_record.occurrences
        )
        return set(chain.from_iterable(chain(tp_files, fp_files)))


# Backwards compatibility alias (deprecated)
HydratedSpecimen = HydratedSnapshot
