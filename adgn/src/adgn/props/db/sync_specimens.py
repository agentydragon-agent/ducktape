"""Sync specimens table from splits.py source of truth.

Auto-syncs on first DB operation per process (cached).
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
import logging
from pathlib import Path

from adgn.props.db import get_session
from adgn.props.db.models import Specimen
from adgn.props.specimens.registry import SpecimenRegistry
from adgn.props.splits import SPECIMEN_SPLITS

logger = logging.getLogger(__name__)


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


@lru_cache(maxsize=1)
async def ensure_specimens_synced() -> dict[str, int]:
    """Ensure specimens table exactly matches splits.py SPECIMEN_SPLITS.

    Runs once per process (cached). Safe to call before any DB operation.

    Returns:
        Stats dict: {"added": int, "updated": int, "deleted": int, "total": int}
    """
    # Create registry once at the start
    registry = SpecimenRegistry.from_package_resources()

    with get_session() as session:
        # Fast path: if count matches, assume synced
        existing_count = session.query(Specimen).count()
        if existing_count == len(SPECIMEN_SPLITS):
            logger.debug(f"Specimens already synced ({existing_count} specimens)")
            return {"added": 0, "updated": 0, "deleted": 0, "total": existing_count}

        # Full sync: make DB exactly match source
        logger.info(f"Syncing specimens table (source: {len(SPECIMEN_SPLITS)} specimens, DB: {existing_count})...")

        db_specimens = {s.specimen_slug: s for s in session.query(Specimen).all()}
        source_slugs = set(SPECIMEN_SPLITS.keys())
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
        all_labeled_files_paths = await _load_all_labeled_files(list(SPECIMEN_SPLITS.keys()), registry)

        for slug, split in SPECIMEN_SPLITS.items():
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

        logger.info(
            f"Specimens synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={len(SPECIMEN_SPLITS)} total"
        )
        return {"added": added, "updated": updated, "deleted": deleted, "total": len(SPECIMEN_SPLITS)}


async def force_sync_specimens() -> dict[str, int]:
    """Force re-sync of specimens table (clears cache).

    Use this for manual sync commands or when cache must be bypassed.

    Returns:
        Stats dict from ensure_specimens_synced()
    """
    # Clear the cache
    ensure_specimens_synced.cache_clear()
    # Run sync
    return await ensure_specimens_synced()
