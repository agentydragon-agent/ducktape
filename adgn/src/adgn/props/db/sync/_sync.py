"""Sync snapshots, issues, and model metadata from filesystem to database.

Replaces sync_specimens.py with new snapshot-based schema.
Includes model metadata sync (previously in sync_model_metadata.py).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
import yaml

from adgn.openai_utils.model_metadata import MODEL_METADATA
from adgn.props.db import get_session
from adgn.props.db.models import FalsePositive, ModelMetadata, Snapshot, TruePositive
from adgn.props.files_hash import hash_file_set
from adgn.props.ids import SnapshotSlug
from adgn.props.models.snapshot import SnapshotDoc
from adgn.props.prop_utils import specimens_definitions_root
from adgn.props.splits import Split

from ._loader import FilesystemLoader

logger = logging.getLogger(__name__)


def get_specimens_base_path() -> Path:
    """Get specimens base path from ADGN_PROPS_SPECIMENS_ROOT environment variable.

    Returns:
        Path to specimens directory

    Raises:
        ValueError: If ADGN_PROPS_SPECIMENS_ROOT environment variable not set
        FileNotFoundError: If specimens directory doesn't exist or missing required files
    """
    return specimens_definitions_root()


def load_manifests_from_yaml(base_path: Path) -> dict[SnapshotSlug, SnapshotDoc]:
    """Load snapshot manifests from snapshots.yaml.

    For use by sync code and tests that validate source files.
    Runtime code should query the database instead.

    Args:
        base_path: Specimens base directory containing snapshots.yaml

    Returns:
        Dict mapping snapshot slug to manifest

    Raises:
        FileNotFoundError: If snapshots.yaml doesn't exist
    """
    snapshots_yaml = base_path / "snapshots.yaml"
    if not snapshots_yaml.exists():
        raise FileNotFoundError(f"snapshots.yaml not found at {snapshots_yaml}")

    raw = yaml.safe_load(snapshots_yaml.read_text(encoding="utf-8")) or {}
    adapter = TypeAdapter(dict[SnapshotSlug, SnapshotDoc])
    return adapter.validate_python(raw)


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


def sync_snapshots_to_db(session: Session, base_path: Path) -> SyncStats:
    """Sync snapshots from filesystem to database.

    Loads snapshots from specimens/snapshots.yaml and upserts to snapshots table.

    Args:
        session: SQLAlchemy session
        base_path: Specimens base directory containing snapshots.yaml

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """

    # Load snapshots from YAML
    snapshots = load_manifests_from_yaml(base_path)

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


def sync_issues_to_db(session: Session, base_path: Path) -> SyncStats:
    """Sync issues and false positives from filesystem to database.

    For each snapshot, loads issues from specimens/{slug}/issues/*.libsonnet
    and upserts to issues and false_positives tables.

    Args:
        session: SQLAlchemy session
        base_path: Specimens base directory

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """

    # Get snapshot slugs from YAML
    manifests = load_manifests_from_yaml(base_path)
    snapshots = list(manifests.keys())

    # Load issues from base path
    loader = FilesystemLoader(base_path)

    # Track stats across both TPs and FPs
    total = 0
    added = 0
    updated = 0
    deleted = 0

    # Get existing issues and FPs from DB

    existing_issues = {(i.snapshot_slug, i.tp_id): i for i in session.query(TruePositive).all()}
    existing_fps = {(fp.snapshot_slug, fp.fp_id): fp for fp in session.query(FalsePositive).all()}

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


def generate_examples_for_snapshot(session: Session, slug: SnapshotSlug, split: Split) -> list[tuple[list[str], str]]:
    """Generate training examples for a snapshot from expect_caught_from data.

    For TRAIN snapshots:
        - One example per unique expect_caught_from trigger set
        - Plus one full-specimen example (all files with issues)

    For VALID/TEST snapshots:
        - Only full-specimen example

    Returns examples ordered by files_hash (deterministic, required for GEPA checkpoint resume).

    Args:
        session: SQLAlchemy session
        slug: Snapshot slug
        split: Train/valid/test split

    Returns:
        List of (files, files_hash) tuples for this snapshot, ordered by files_hash
    """
    # Get all issues for this snapshot
    snapshot = session.query(Snapshot).filter_by(slug=slug).one()
    true_positives = snapshot.true_positives
    false_positives = snapshot.false_positives

    # Collect all files with issues (for full-specimen example)
    all_files: set[Path] = set()
    for tp in true_positives:
        for tp_occ in tp.occurrences:
            all_files.update(tp_occ.files.keys())
    for fp in false_positives:
        for fp_occ in fp.occurrences:
            all_files.update(fp_occ.files.keys())

    # Collect unique file sets (set of frozenset of Paths)
    # Keep as Path objects until hashing to avoid premature string conversion
    file_sets: set[frozenset[Path]] = set()

    if split == Split.TRAIN:
        # Collect all unique trigger sets from expect_caught_from
        for tp in true_positives:
            for occurrence in tp.occurrences:
                for trigger_set in occurrence.expect_caught_from:
                    file_sets.add(trigger_set)

    # Always add full-specimen example (terminal metric) - automatically dedupes
    file_sets.add(frozenset(all_files))

    # Convert to output format with hashes, then sort by hash (deterministic ordering)
    examples_with_hashes: list[tuple[list[str], str]] = []
    for file_set in file_sets:
        # Compute hash from Path objects
        files_hash = hash_file_set(file_set)
        # Convert to sorted string list for storage
        files_list = sorted(str(p) for p in file_set)
        examples_with_hashes.append((files_list, files_hash))

    # Sort by files_hash for deterministic ordering (required for GEPA checkpoint resume)
    examples_with_hashes.sort(key=lambda x: x[1])

    return examples_with_hashes


def sync_examples_to_db(session: Session, base_path: Path) -> SyncStats:
    """Sync training examples to database (auto-generated from expect_caught_from data).

    For each snapshot:
    - TRAIN: One example per unique expect_caught_from trigger set + full-specimen example
    - VALID/TEST: Only full-specimen example (terminal metric)

    No YAML loading - examples are purely derived from issue definitions.

    Args:
        session: SQLAlchemy session
        base_path: Specimens base directory (used to load snapshot manifests)

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """
    from adgn.props.db.models import Example

    # Load snapshot manifests to get slugs and splits
    manifests = load_manifests_from_yaml(base_path)

    # Get existing examples from DB
    existing_examples = {(ex.snapshot_slug, ex.files_hash): ex for ex in session.query(Example).all()}

    # Track which examples we've seen (to detect deletions)
    seen_example_keys = set()

    # Track stats
    total = 0
    added = 0
    updated = 0
    deleted = 0

    # Collect all examples to upsert (use dict to ensure uniqueness by key)
    examples_to_upsert: dict[tuple[SnapshotSlug, str], dict] = {}

    # Process each snapshot
    for slug, manifest in manifests.items():
        # Generate examples for this snapshot
        examples = generate_examples_for_snapshot(session, slug, manifest.split)

        for files_list, files_hash in examples:
            key = (slug, files_hash)
            seen_example_keys.add(key)

            if key not in existing_examples:
                # New example
                logger.debug(f"Adding example: {slug} (hash={files_hash[:8]}...)")
                examples_to_upsert[key] = {"snapshot_slug": slug, "files_hash": files_hash, "files": files_list}
                added += 1
            else:
                # Existing example - check if update needed
                existing = existing_examples[key]
                if existing.files != files_list:
                    logger.debug(f"Updating example files: {slug} (hash={files_hash[:8]}...)")
                    examples_to_upsert[key] = {"snapshot_slug": slug, "files_hash": files_hash, "files": files_list}
                    updated += 1

            total += 1

    # Batch upsert using PostgreSQL's ON CONFLICT
    if examples_to_upsert:
        stmt = insert(Example).values(list(examples_to_upsert.values()))
        stmt = stmt.on_conflict_do_update(
            index_elements=["snapshot_slug", "files_hash"],
            set_={"files": stmt.excluded.files, "updated_at": func.now()},
        )
        session.execute(stmt)

    # Delete orphaned examples (in DB but not in generated set)
    for key in set(existing_examples.keys()) - seen_example_keys:
        slug, files_hash = key
        logger.info(f"Deleting orphaned example: {slug} (hash={files_hash[:8]}...)")
        session.delete(existing_examples[key])
        deleted += 1

    session.commit()
    logger.info(f"Examples synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={total} total")
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
