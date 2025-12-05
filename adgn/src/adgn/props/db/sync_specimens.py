"""Sync snapshots table from snapshots.yaml."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path

from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.ids import SnapshotSlug
from adgn.props.snapshot_registry import SnapshotRegistry

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


async def _load_all_labeled_files(
    slugs: list[SnapshotSlug], registry: SnapshotRegistry
) -> dict[SnapshotSlug, set[Path]]:
    """Load labeled_files (files with ground truth issues) for all snapshots in parallel.

    Args:
        slugs: List of specimen slugs to load
        registry: SnapshotRegistry instance for loading snapshots

    Returns:
        Dict mapping slug -> set of file paths that appear in issue definitions
    """

    async def load_one(slug: SnapshotSlug) -> tuple[SnapshotSlug, set[Path]]:
        """Load labeled_files for a single specimen."""
        async with registry.load_and_hydrate(slug) as hydrated:
            # Extract all files referenced in issue definitions (TPs and FPs)
            def files_from_issue_records(records: dict) -> set[Path]:
                return {
                    file_path
                    for issue_record in records.values()
                    for occurrence in issue_record.occurrences
                    for file_path in occurrence.files
                }

            return slug, files_from_issue_records(hydrated.record.true_positives) | files_from_issue_records(
                hydrated.record.false_positives
            )

    # Load all snapshots in parallel
    results = await asyncio.gather(*[load_one(slug) for slug in slugs])
    return dict(results)


async def sync_snapshots() -> SyncStats:
    """Sync snapshots table from specimen manifests.

    Ensures database exactly matches the source of truth (manifest files).

    Returns:
        Statistics about what changed
    """
    # Create registry once at the start
    registry = SnapshotRegistry.from_package_resources()

    # Get all snapshot slugs and build split mapping
    source_slugs = registry.snapshot_slugs
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
            split = registry.get_split(slug)
            _manifest_path, manifest = registry.load_manifest_only(slug)

            if slug not in db_slugs:
                logger.debug(f"  Adding snapshot: {slug} (split={split.value})")
                session.add(Snapshot(slug=slug, split=split.value, source=manifest.source, bundle=manifest.bundle))
                added += 1
            else:
                # Existing snapshot - check if split needs update
                db_row = session.query(Snapshot).filter_by(slug=slug).one()
                if db_row.split != split.value:
                    logger.info(f"  Updating snapshot split: {slug} ({db_row.split} -> {split.value})")
                    db_row.split = split.value
                    updated += 1

        session.commit()

        logger.info(f"Snapshots synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={source_count} total")
        return SyncStats(added=added, updated=updated, deleted=deleted, total=source_count)
