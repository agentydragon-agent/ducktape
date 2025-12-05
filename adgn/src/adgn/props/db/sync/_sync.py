"""Sync snapshots, issues, and model metadata from filesystem to database.

Replaces sync_specimens.py with new snapshot-based schema.
Includes model metadata sync (previously in sync_model_metadata.py).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from adgn.openai_utils.model_metadata import MODEL_METADATA
from adgn.props.db import get_session
from adgn.props.db.models import CriticScopeDB, FalsePositive, ModelMetadata, Snapshot, TruePositive
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import ALL_FILES_WITH_ISSUES, CriticScopeSpec
from adgn.props.snapshot_registry import SnapshotRegistry

from ._loader import FilesystemLoader

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


def sync_snapshots_to_db(session: Session, registry: SnapshotRegistry) -> SyncStats:
    """Sync snapshots from filesystem to database.

    Loads snapshots from specimens/snapshots.yaml and upserts to snapshots table.

    Args:
        session: SQLAlchemy session
        registry: Registry to sync from

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """

    # Load snapshots from registry
    snapshots = {}
    for slug in registry.snapshot_slugs:
        _snapshot_path, manifest = registry.load_manifest_only(slug)
        snapshots[slug] = manifest

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
    for slug, manifest in snapshots.items():
        # Convert Pydantic model to dict for upsert
        snapshot_data = {
            "slug": slug,
            "split": manifest.split,
            "source": manifest.source.model_dump(mode="json"),
            "bundle": manifest.bundle.model_dump(mode="json") if manifest.bundle else None,
        }

        if slug not in db_slugs:
            # New snapshot - insert
            logger.debug(f"Adding snapshot: {slug} (split={manifest.split})")
            stmt = insert(Snapshot).values(**snapshot_data)
            session.execute(stmt)
            added += 1
        else:
            # Existing snapshot - check if update needed
            existing_snap = existing[slug]
            needs_update = False

            if existing_snap.split != manifest.split:
                logger.info(f"Updating snapshot split: {slug} ({existing_snap.split} -> {manifest.split})")
                needs_update = True

            # For source/bundle comparison, use model_dump for consistent comparison
            existing_source = existing_snap.source
            new_source = manifest.source.model_dump(mode="json")
            if existing_source != new_source:
                logger.debug(f"Updating snapshot source: {slug}")
                needs_update = True

            existing_bundle = existing_snap.bundle
            new_bundle = manifest.bundle.model_dump(mode="json") if manifest.bundle else None
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


def sync_issues_to_db(session: Session, registry: SnapshotRegistry) -> SyncStats:
    """Sync issues and false positives from filesystem to database.

    For each snapshot, loads issues from specimens/{slug}/*.libsonnet
    and upserts to issues and false_positives tables.

    Args:
        session: SQLAlchemy session
        registry: Registry to sync from

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """

    # Get snapshot slugs from registry
    snapshots = list(registry.snapshot_slugs)

    # Load issues from registry's base path
    loader = FilesystemLoader(registry.base_path)

    # Track stats across both TPs and FPs
    total = 0
    added = 0
    updated = 0
    deleted = 0

    # Get existing issues and FPs from DB

    existing_issues = {(SnapshotSlug(i.snapshot_slug), i.tp_id): i for i in session.query(TruePositive).all()}
    existing_fps = {(SnapshotSlug(fp.snapshot_slug), fp.fp_id): fp for fp in session.query(FalsePositive).all()}

    # Track which issues/FPs we've seen (to detect deletions)
    seen_issue_keys = set()
    seen_fp_keys = set()

    # Process each snapshot
    for slug in snapshots:
        try:
            true_positives, false_positives = loader.load_issues_for_snapshot(slug)
        except FileNotFoundError:
            # No issues directory for this snapshot - skip
            logger.debug(f"No issues found for snapshot: {slug}")
            continue
        except Exception as e:
            logger.error(f"Failed to load issues for {slug}: {e}")
            raise

        # Sync true positives
        for issue in true_positives:
            key = (issue.snapshot_slug, issue.tp_id)
            seen_issue_keys.add(key)

            if key not in existing_issues:
                # New issue - create ORM instance directly from Pydantic
                logger.debug(f"Adding issue: {issue.snapshot_slug}/{issue.tp_id}")
                orm_issue = TruePositive(
                    snapshot_slug=issue.snapshot_slug,
                    tp_id=issue.tp_id,
                    rationale=issue.rationale,
                    occurrences=issue.occurrences,  # PydanticColumn handles serialization
                )
                session.add(orm_issue)
                added += 1
                total += 1
            else:
                # Existing issue - check if update needed
                existing = existing_issues[key]
                needs_update = False

                if existing.rationale != issue.rationale:
                    logger.debug(f"Updating issue rationale: {key}")
                    needs_update = True

                # Compare occurrences (PydanticColumn returns typed objects)
                if existing.occurrences != issue.occurrences:
                    logger.debug(f"Updating issue occurrences: {key}")
                    needs_update = True

                if needs_update:
                    existing.rationale = issue.rationale
                    existing.occurrences = issue.occurrences
                    updated += 1
                    total += 1
                else:
                    total += 1

        # Sync false positives
        for fp in false_positives:
            key = (fp.snapshot_slug, fp.fp_id)
            seen_fp_keys.add(key)

            if key not in existing_fps:
                # New FP - create ORM instance directly from Pydantic
                logger.debug(f"Adding false positive: {fp.snapshot_slug}/{fp.fp_id}")
                orm_fp = FalsePositive(
                    snapshot_slug=fp.snapshot_slug,
                    fp_id=fp.fp_id,
                    rationale=fp.rationale,
                    occurrences=fp.occurrences,  # PydanticColumn handles serialization
                )
                session.add(orm_fp)
                added += 1
                total += 1
            else:
                # Existing FP - check if update needed
                existing_fp = existing_fps[key]
                needs_update = False

                if existing_fp.rationale != fp.rationale:
                    logger.debug(f"Updating FP rationale: {key}")
                    needs_update = True

                # Compare occurrences (PydanticColumn returns typed objects)
                if existing_fp.occurrences != fp.occurrences:
                    logger.debug(f"Updating FP occurrences: {key}")
                    needs_update = True

                if needs_update:
                    existing_fp.rationale = fp.rationale
                    existing_fp.occurrences = fp.occurrences
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


def _hash_critic_scope_files(files: CriticScopeSpec) -> str:
    """Calculate SHA256 hash of critic scope files for uniqueness constraint.

    Ensures deterministic hashing across Python runs by:
    - Using special token for "all" sentinel
    - Sorting file paths for set[Path] case

    Args:
        files: CriticScopeSpec (set[Path] or "all" sentinel)

    Returns:
        64-character SHA256 hex digest
    """
    if files == ALL_FILES_WITH_ISSUES:
        # Special case for "all" sentinel
        return hashlib.sha256(b"__ALL_FILES_WITH_ISSUES__").hexdigest()

    # Sort paths for deterministic hash
    sorted_files = sorted(str(p) for p in files)
    content = "\n".join(sorted_files).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def sync_critic_scopes_to_db(session: Session, registry: SnapshotRegistry) -> SyncStats:
    """Sync critic scopes from filesystem to database.

    Loads critic scopes from specimens/critic_scopes.yaml and upserts to
    critic_scopes table with proper hash calculation for uniqueness.

    Args:
        session: SQLAlchemy session
        registry: Registry to sync from

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """
    # Load critic scopes from YAML
    loader = FilesystemLoader(registry.base_path)
    scopes_by_slug = loader.load_critic_scopes()

    # Get existing critic scopes from DB
    existing_scopes = {(scope.snapshot_slug, scope.files_hash): scope for scope in session.query(CriticScopeDB).all()}

    # Track which scopes we've seen (to detect deletions)
    seen_scope_keys = set()

    # Track stats
    total = 0
    added = 0
    updated = 0
    deleted = 0

    # Process each snapshot's critic scopes
    for slug, scope_list in scopes_by_slug.items():
        for scope in scope_list:
            # Calculate hash for uniqueness
            files_hash = _hash_critic_scope_files(scope.files)
            key = (slug, files_hash)
            seen_scope_keys.add(key)

            if key not in existing_scopes:
                # New critic scope - create ORM instance
                logger.debug(f"Adding critic scope: {slug} (hash={files_hash[:8]}...)")
                orm_scope = CriticScopeDB(snapshot_slug=slug, files=scope.files, files_hash=files_hash)
                session.add(orm_scope)
                added += 1
                total += 1
            else:
                # Existing critic scope - check if update needed
                existing = existing_scopes[key]
                needs_update = False

                # Check if files changed (though hash should catch this)
                if existing.files != scope.files:
                    logger.debug(f"Updating critic scope files: {slug}")
                    existing.files = scope.files
                    needs_update = True

                if needs_update:
                    updated += 1

                total += 1

    # Delete orphaned critic scopes (in DB but not in source)
    for key in set(existing_scopes.keys()) - seen_scope_keys:
        slug, files_hash = key
        logger.info(f"Deleting orphaned critic scope: {slug} (hash={files_hash[:8]}...)")
        session.delete(existing_scopes[key])
        deleted += 1

    session.commit()
    logger.info(f"Critic scopes synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={total} total")
    return SyncStats(total=total, added=added, updated=updated, deleted=deleted)


# ============================================================================
# Model Metadata Sync (from MODEL_METADATA source of truth)
# ============================================================================


@dataclass
class ModelMetadataSyncStats:
    """Statistics from a model metadata sync operation."""

    total: int
    added: int
    updated: int
    deleted: int

    @property
    def summary_text(self) -> str:
        """Format as human-readable summary."""
        return f"{self.total} models (+{self.added}, ~{self.updated}, -{self.deleted})"


def sync_model_metadata() -> ModelMetadataSyncStats:
    """Sync model_metadata table from MODEL_METADATA source.

    Opens its own session internally (legacy interface for backward compatibility).

    Returns:
        Statistics about what changed
    """
    with get_session() as session:
        return sync_model_metadata_with_session(session)


def sync_model_metadata_with_session(session: Session) -> ModelMetadataSyncStats:
    """Sync model_metadata table from MODEL_METADATA source using provided session.

    Ensures database exactly matches the source of truth.

    Args:
        session: Active database session

    Returns:
        Statistics about what changed
    """
    # Fast path: if count matches, assume synced
    existing_count = session.query(ModelMetadata).count()
    if existing_count == len(MODEL_METADATA):
        logger.debug(f"Model metadata already synced ({existing_count} models)")
        return ModelMetadataSyncStats(added=0, updated=0, deleted=0, total=existing_count)

    # Full sync: make DB exactly match source
    logger.info(f"Syncing model_metadata table (source: {len(MODEL_METADATA)} models, DB: {existing_count})...")

    db_models = {m.model_id: m for m in session.query(ModelMetadata).all()}
    source_model_ids = set(MODEL_METADATA.keys())
    db_model_ids = set(db_models.keys())

    added = 0
    updated = 0
    deleted = 0

    # Delete orphaned models (in DB but not in source)
    for model_id in db_model_ids - source_model_ids:
        logger.info(f"  Deleting orphaned model: {model_id}")
        session.delete(db_models[model_id])
        deleted += 1

    # Add/update from source using merge (handles both cases)
    for model_id, meta in MODEL_METADATA.items():
        is_new = model_id not in db_model_ids
        session.merge(
            ModelMetadata(
                model_id=model_id,
                input_usd_per_1m_tokens=meta.input_usd_per_1m_tokens,
                cached_input_usd_per_1m_tokens=meta.cached_input_usd_per_1m_tokens,
                output_usd_per_1m_tokens=meta.output_usd_per_1m_tokens,
                context_window_tokens=meta.context_window_tokens,
                max_output_tokens=meta.max_output_tokens,
            )
        )
        if is_new:
            logger.debug(f"  Adding model: {model_id}")
            added += 1
        else:
            # Note: merge() updates if changed; count all as updated for stats
            updated += 1

    session.flush()

    logger.info(
        f"Model metadata synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={len(MODEL_METADATA)} total"
    )
    return ModelMetadataSyncStats(added=added, updated=updated, deleted=deleted, total=len(MODEL_METADATA))
