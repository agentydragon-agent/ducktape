"""Sync snapshots and issues from filesystem to database.

Replaces sync_specimens.py with new snapshot-based schema.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from adgn.props.db.models import FalsePositive, Issue, Snapshot
from adgn.props.loaders.filesystem import FilesystemLoader

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics from a sync operation."""

    total: int
    added: int
    updated: int
    deleted: int

    @property
    def summary_text(self) -> str:
        """Format as human-readable summary."""
        return f"{self.total} total (+{self.added}, ~{self.updated}, -{self.deleted})"


def sync_snapshots_to_db(session: Session) -> SyncStats:
    """Sync snapshots from filesystem to database.

    Loads snapshots from specimens/snapshots.yaml and upserts to snapshots table.

    Args:
        session: SQLAlchemy session

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """
    # Get specimens directory from package resources
    specimens_dir = Path(__file__).resolve().parent.parent / "specimens"
    if not specimens_dir.exists():
        raise FileNotFoundError(f"Specimens directory not found: {specimens_dir}")

    # Load snapshots from filesystem
    loader = FilesystemLoader(specimens_dir)
    snapshots = loader.load_snapshots()

    # Get existing snapshots from DB
    existing = {s.slug: s for s in session.query(Snapshot).all()}
    source_slugs = set(snapshots.keys())
    db_slugs = set(existing.keys())

    # Track stats
    added = 0
    updated = 0
    deleted = 0

    # Delete orphaned snapshots (in DB but not in source)
    for slug in db_slugs - source_slugs:
        logger.info(f"Deleting orphaned snapshot: {slug}")
        session.delete(existing[slug])
        deleted += 1

    # Add/update snapshots from source
    for slug, snapshot in snapshots.items():
        # Convert Pydantic model to dict for upsert
        snapshot_data = {
            "slug": snapshot.slug,
            "split": snapshot.split,
            "source": snapshot.source.model_dump(mode="json"),
            "bundle": snapshot.bundle.model_dump(mode="json") if snapshot.bundle else None,
        }

        if slug not in db_slugs:
            # New snapshot - insert
            logger.debug(f"Adding snapshot: {slug} (split={snapshot.split})")
            stmt = insert(Snapshot).values(**snapshot_data)
            session.execute(stmt)
            added += 1
        else:
            # Existing snapshot - check if update needed
            existing_snap = existing[slug]
            needs_update = False

            if existing_snap.split != snapshot.split:
                logger.info(f"Updating snapshot split: {slug} ({existing_snap.split} -> {snapshot.split})")
                needs_update = True

            # For source/bundle comparison, use model_dump for consistent comparison
            existing_source = existing_snap.source
            new_source = snapshot.source.model_dump(mode="json")
            if existing_source != new_source:
                logger.debug(f"Updating snapshot source: {slug}")
                needs_update = True

            existing_bundle = existing_snap.bundle
            new_bundle = snapshot.bundle.model_dump(mode="json") if snapshot.bundle else None
            if existing_bundle != new_bundle:
                logger.debug(f"Updating snapshot bundle: {slug}")
                needs_update = True

            if needs_update:
                stmt = (
                    insert(Snapshot)
                    .values(**snapshot_data)
                    .on_conflict_do_update(index_elements=["slug"], set_=snapshot_data)
                )
                session.execute(stmt)
                updated += 1

    session.commit()
    total = len(snapshots)
    logger.info(f"Snapshots synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={total} total")
    return SyncStats(total=total, added=added, updated=updated, deleted=deleted)


def sync_issues_to_db(session: Session) -> SyncStats:
    """Sync issues and false positives from filesystem to database.

    For each snapshot, loads issues from specimens/{slug}/*.libsonnet
    and upserts to issues and false_positives tables.

    Args:
        session: SQLAlchemy session

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """
    # Get specimens directory from package resources
    specimens_dir = Path(__file__).resolve().parent.parent / "specimens"
    if not specimens_dir.exists():
        raise FileNotFoundError(f"Specimens directory not found: {specimens_dir}")

    # Load snapshots to get list of slugs
    loader = FilesystemLoader(specimens_dir)
    snapshots = loader.load_snapshots()

    # Track stats across both TPs and FPs
    total = 0
    added = 0
    updated = 0
    deleted = 0

    # Get existing issues and FPs from DB
    existing_issues = {(i.snapshot_slug, i.issue_id): i for i in session.query(Issue).all()}
    existing_fps = {(fp.snapshot_slug, fp.fp_id): fp for fp in session.query(FalsePositive).all()}

    # Track which issues/FPs we've seen (to detect deletions)
    seen_issue_keys = set()
    seen_fp_keys = set()

    # Process each snapshot
    for slug in snapshots.keys():
        try:
            issues, false_positives = loader.load_issues_for_snapshot(slug)
        except FileNotFoundError:
            # No issues directory for this snapshot - skip
            logger.debug(f"No issues found for snapshot: {slug}")
            continue
        except Exception as e:
            logger.error(f"Failed to load issues for {slug}: {e}")
            raise

        # Sync true positives (issues)
        for issue in issues:
            key = (issue.snapshot_slug, issue.issue_id)
            seen_issue_keys.add(key)

            # Convert Pydantic model to dict for upsert
            # Use model_dump() for JSONB fields to get proper serialization
            issue_data = {
                "snapshot_slug": issue.snapshot_slug,
                "issue_id": issue.issue_id,
                "rationale": issue.rationale,
                "occurrences": [occ.model_dump(mode="json") for occ in issue.occurrences],
            }

            if key not in existing_issues:
                # New issue - insert
                logger.debug(f"Adding issue: {issue.snapshot_slug}/{issue.issue_id}")
                stmt = insert(Issue).values(**issue_data)
                session.execute(stmt)
                added += 1
                total += 1
            else:
                # Existing issue - check if update needed
                existing = existing_issues[key]
                needs_update = False

                if existing.rationale != issue.rationale:
                    logger.debug(f"Updating issue rationale: {key}")
                    needs_update = True

                # Compare occurrences (already in dict form in DB)
                new_occurrences = [occ.model_dump(mode="json") for occ in issue.occurrences]
                if existing.occurrences != new_occurrences:
                    logger.debug(f"Updating issue occurrences: {key}")
                    needs_update = True

                if needs_update:
                    stmt = (
                        insert(Issue)
                        .values(**issue_data)
                        .on_conflict_do_update(
                            index_elements=["snapshot_slug", "issue_id"],
                            set_={"rationale": issue_data["rationale"], "occurrences": issue_data["occurrences"]},
                        )
                    )
                    session.execute(stmt)
                    updated += 1
                    total += 1
                else:
                    total += 1

        # Sync false positives
        for fp in false_positives:
            key = (fp.snapshot_slug, fp.fp_id)
            seen_fp_keys.add(key)

            # Convert Pydantic model to dict for upsert
            fp_data = {
                "snapshot_slug": fp.snapshot_slug,
                "fp_id": fp.fp_id,
                "rationale": fp.rationale,
                "occurrences": [occ.model_dump(mode="json") for occ in fp.occurrences],
            }

            if key not in existing_fps:
                # New FP - insert
                logger.debug(f"Adding false positive: {fp.snapshot_slug}/{fp.fp_id}")
                stmt = insert(FalsePositive).values(**fp_data)
                session.execute(stmt)
                added += 1
                total += 1
            else:
                # Existing FP - check if update needed
                existing_fp = existing_fps[key]
                needs_update = False

                if existing_fp.rationale != fp.rationale:
                    logger.debug(f"Updating FP rationale: {key}")
                    needs_update = True

                # Compare occurrences
                new_occurrences = [occ.model_dump(mode="json") for occ in fp.occurrences]
                if existing_fp.occurrences != new_occurrences:
                    logger.debug(f"Updating FP occurrences: {key}")
                    needs_update = True

                if needs_update:
                    stmt = (
                        insert(FalsePositive)
                        .values(**fp_data)
                        .on_conflict_do_update(
                            index_elements=["snapshot_slug", "fp_id"],
                            set_={"rationale": fp_data["rationale"], "occurrences": fp_data["occurrences"]},
                        )
                    )
                    session.execute(stmt)
                    updated += 1
                    total += 1
                else:
                    total += 1

    # Delete orphaned issues (in DB but not in source)
    for key in set(existing_issues.keys()) - seen_issue_keys:
        logger.info(f"Deleting orphaned issue: {key[0]}/{key[1]}")
        session.delete(existing_issues[key])
        deleted += 1

    # Delete orphaned FPs (in DB but not in source)
    for key in set(existing_fps.keys()) - seen_fp_keys:
        logger.info(f"Deleting orphaned false positive: {key[0]}/{key[1]}")
        session.delete(existing_fps[key])
        deleted += 1

    session.commit()
    logger.info(f"Issues synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={total} total")
    return SyncStats(total=total, added=added, updated=updated, deleted=deleted)
