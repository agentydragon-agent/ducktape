"""Hydrated snapshot - source code extraction only (no issues).

Issues must be loaded from database via ORM Snapshot model.
"""

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
    """Hydrated snapshot with source code only (no issues).

    Issues must be loaded from database via ORM Snapshot model.

    Temporary migration note: `record` field still exists for backwards compatibility
    with SnapshotRegistry.load_and_hydrate() during migration. New code should use
    SnapshotHydrator.hydrate() which doesn't include record.

    Example (new code):
        from adgn.props.snapshot_hydrator import SnapshotHydrator
        from adgn.props.db import get_session
        from adgn.props.db.models import Snapshot

        hydrator = SnapshotHydrator.from_package_resources()
        async with hydrator.hydrate("ducktape/2025-11-26-00") as hydrated:
            # Source from hydrator
            workspace = hydrated.content_root
            files = hydrated.all_discovered_files

            # Issues from ORM
            session = get_session()
            snapshot = session.query(Snapshot).filter_by(slug=slug).one()
            tps = snapshot.true_positives
            fps = snapshot.false_positives
    """

    content_root: Path
    all_discovered_files: dict[Path, FileType]
    record: SnapshotRecord | None = None  # Temporary compat field, will be removed

    # Temporary compat properties (delegate to record if present)
    # Will be removed after SnapshotRegistry migration complete
    @property
    def manifest(self) -> SnapshotDoc:
        """Snapshot manifest (source, bundle).

        DEPRECATED: Load manifest separately or use SnapshotHydrator.
        """
        if self.record is None:
            raise AttributeError("HydratedSnapshot.manifest requires record (use SnapshotHydrator + ORM instead)")
        return self.record.manifest

    @property
    def slug(self) -> str:
        """Snapshot slug (e.g., 'ducktape/2025-11-20').

        DEPRECATED: Track slug separately or load from ORM.
        """
        if self.record is None:
            raise AttributeError("HydratedSnapshot.slug requires record (use SnapshotHydrator + ORM instead)")
        return self.record.slug

    @property
    def true_positives(self) -> dict[TruePositiveID, TruePositiveIssue]:
        """True positive issues (canonical ground truth).

        DEPRECATED: Load from database via ORM Snapshot model.
        """
        if self.record is None:
            raise AttributeError("HydratedSnapshot.true_positives requires record (use ORM Snapshot instead)")
        return self.record.true_positives

    @property
    def false_positives(self) -> dict[FalsePositiveID, KnownFalsePositive]:
        """Known false positives.

        DEPRECATED: Load from database via ORM Snapshot model.
        """
        if self.record is None:
            raise AttributeError("HydratedSnapshot.false_positives requires record (use ORM Snapshot instead)")
        return self.record.false_positives

    def files_with_issues(self) -> set[Path]:
        """Return files that have known ground truth TP or FP issues.

        DEPRECATED: Use ORM Snapshot.files_with_issues() instead.

        Returns:
            Set of relative paths mentioned in issues or false_positives.
        """
        if self.record is None:
            raise AttributeError("HydratedSnapshot.files_with_issues requires record (use ORM Snapshot instead)")
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
