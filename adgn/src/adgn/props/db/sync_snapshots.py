"""Sync snapshots table from snapshots.yaml."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path

from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.db.sync import get_specimens_base_path, load_manifests_from_yaml
from adgn.props.ids import SnapshotSlug

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics from a snapshot sync operation."""

    total: int
    added: int
    updated: int
    deleted: int

    @property
    def summary_text(self) -> str:
        """Format as human-readable summary."""
        return f"{self.total} snapshots (+{self.added}, ~{self.updated}, -{self.deleted})"


async def _load_all_labeled_files(slugs: list[SnapshotSlug]) -> dict[SnapshotSlug, set[Path]]:
    """Load labeled_files (files with ground truth issues) for all snapshots in parallel.

    Args:
        slugs: List of specimen slugs to load

    Returns:
        Dict mapping slug -> set of file paths that appear in issue definitions
    """

    async def load_one(slug: SnapshotSlug) -> tuple[SnapshotSlug, set[Path]]:
        """Load labeled_files for a single specimen."""
        # Load issue data from database (not from hydrated snapshot)
        with get_session() as session:
            snapshot_orm = session.query(Snapshot).filter_by(slug=slug).one()

            # Extract all files referenced in issue definitions (TPs and FPs)
            def files_from_orm_issues(issues) -> set[Path]:
                return {
                    Path(file_path)
                    for issue in issues
                    for occurrence in issue.occurrences
                    for file_path in occurrence.files
                }

            tp_files = files_from_orm_issues(snapshot_orm.true_positives)
            fp_files = files_from_orm_issues(snapshot_orm.false_positives)

            return slug, tp_files | fp_files

    # Load all snapshots in parallel
    results = await asyncio.gather(*[load_one(slug) for slug in slugs])
    return dict(results)


async def sync_snapshots() -> SyncStats:
    """Sync snapshots table from specimen manifests.

    Ensures database exactly matches the source of truth (manifest files).

    Returns:
        Statistics about what changed
    """
    # Load manifests from snapshots.yaml
    base_path = get_specimens_base_path()
    manifests = load_manifests_from_yaml(base_path)

    # Get all snapshot slugs
    source_slugs = set(manifests.keys())
    source_count = len(source_slugs)

    with get_session() as session:
        # Fast path: if count matches, assume synced
        existing_count = session.query(Snapshot).count()
        if existing_count == source_count:
            logger.debug(f"Snapshots already synced ({existing_count} snapshots)")
            return SyncStats(added=0, updated=0, deleted=0, total=existing_count)

        # Full sync: make DB exactly match source
        logger.info(f"Syncing snapshots table (source: {source_count} snapshots, DB: {existing_count})...")

        db_slugs = {s.slug for s in session.query(Snapshot).all()}

        added = 0
        updated = 0
        deleted = 0

        # Delete orphaned snapshots (in DB but not in source)
        for slug in db_slugs - source_slugs:
            logger.info(f"  Deleting orphaned snapshot: {slug}")
            db_row = session.query(Snapshot).filter_by(slug=slug).one()
            session.delete(db_row)
            deleted += 1

        # Add/update from source
        # NOTE: labeled_files sync is disabled - Snapshot model doesn't have this field.
        # Issue file tracking is now done via the Issue/FalsePositive tables.
        for slug in source_slugs:
            manifest = manifests[slug]
            split = manifest.split

            if slug not in db_slugs:
                logger.debug(f"  Adding snapshot: {slug} (split={split.value})")
                session.add(Snapshot(slug=slug, split=split, source=manifest.source, bundle=manifest.bundle))
                added += 1
            else:
                # Existing snapshot - check if split needs update
                db_row = session.query(Snapshot).filter_by(slug=slug).one()
                if db_row.split != split:
                    logger.info(f"  Updating snapshot split: {slug} ({db_row.split.value} -> {split.value})")
                    db_row.split = split
                    updated += 1

        session.commit()

        logger.info(f"Snapshots synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={source_count} total")
        return SyncStats(added=added, updated=updated, deleted=deleted, total=source_count)
