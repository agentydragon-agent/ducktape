"""Sync specimens table from specimen manifest splits."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path

from adgn.props.db import get_session
from adgn.props.db.models import Specimen
from adgn.props.specimens.registry import SpecimenRegistry

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics from a specimen sync operation."""

    total: int
    added: int
    updated: int
    deleted: int

    @property
    def summary_text(self) -> str:
        """Format as human-readable summary."""
        return f"{self.total} specimens (+{self.added}, ~{self.updated}, -{self.deleted})"


async def _load_all_labeled_files(slugs: list[str], registry: SpecimenRegistry) -> dict[str, set[Path]]:
    """Load labeled_files (files with ground truth issues) for all specimens in parallel.

    Args:
        slugs: List of specimen slugs to load
        registry: SpecimenRegistry instance for loading specimens

    Returns:
        Dict mapping slug -> set of file paths that appear in issue definitions
    """

    async def load_one(slug: str) -> tuple[str, set[Path]]:
        """Load labeled_files for a single specimen."""
        async with registry.load_and_hydrate(slug) as hydrated:
            # Extract all files referenced in issue definitions (TPs and FPs)
            def files_from_issue_records(records: dict) -> set[Path]:
                return {
                    file_path
                    for issue_record in records.values()
                    for occurrence in issue_record.instances
                    for file_path in occurrence.files
                }

            return slug, files_from_issue_records(hydrated.record.issues) | files_from_issue_records(
                hydrated.record.false_positives
            )

    # Load all specimens in parallel
    results = await asyncio.gather(*[load_one(slug) for slug in slugs])
    return dict(results)


async def sync_specimens() -> SyncStats:
    """Sync specimens table from specimen manifests.

    Ensures database exactly matches the source of truth (manifest files).

    Returns:
        Statistics about what changed
    """
    # Create registry once at the start
    registry = SpecimenRegistry.from_package_resources()

    # Get all specimen slugs and build split mapping
    source_slugs = registry.specimen_slugs
    source_count = len(source_slugs)

    with get_session() as session:
        # Fast path: if count matches, assume synced
        existing_count = session.query(Specimen).count()
        if existing_count == source_count:
            logger.debug(f"Specimens already synced ({existing_count} specimens)")
            return SyncStats(added=0, updated=0, deleted=0, total=existing_count)

        # Full sync: make DB exactly match source
        logger.info(f"Syncing specimens table (source: {source_count} specimens, DB: {existing_count})...")

        db_specimens = {s.specimen_slug: s for s in session.query(Specimen).all()}
        db_slugs = set(db_specimens.keys())

        added = 0
        updated = 0
        deleted = 0

        # Delete orphaned specimens (in DB but not in source)
        for slug in db_slugs - source_slugs:
            logger.info(f"  Deleting orphaned specimen: {slug}")
            session.delete(db_specimens[slug])
            deleted += 1

        # Add/update from source (populate labeled_files from issue definitions)
        # Batch load all labeled_files upfront
        all_labeled_files_paths = await _load_all_labeled_files(list(source_slugs), registry)

        for slug in source_slugs:
            split = registry.get_split(slug)
            labeled_files_paths = all_labeled_files_paths.get(slug, set())
            # Convert to sorted list of strings for database storage
            labeled_files = sorted(str(p) for p in labeled_files_paths)

            if slug not in db_slugs:
                logger.debug(f"  Adding specimen: {slug} (split={split.value}, {len(labeled_files)} files)")
                session.add(Specimen(specimen_slug=slug, split=split.value, labeled_files=labeled_files))
                added += 1
            else:
                # Update split or labeled_files if changed
                needs_update = False
                if db_specimens[slug].split != split.value:
                    logger.info(f"  Updating specimen split: {slug} ({db_specimens[slug].split} -> {split.value})")
                    db_specimens[slug].split = split.value
                    needs_update = True
                if db_specimens[slug].labeled_files != labeled_files:
                    logger.debug(
                        f"  Updating labeled_files: {slug} ({len(db_specimens[slug].labeled_files)} -> {len(labeled_files)} files)"
                    )
                    db_specimens[slug].labeled_files = labeled_files
                    needs_update = True
                if needs_update:
                    updated += 1

        session.commit()

        logger.info(f"Specimens synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={source_count} total")
        return SyncStats(added=added, updated=updated, deleted=deleted, total=source_count)
