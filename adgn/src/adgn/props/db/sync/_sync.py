"""Sync snapshots, issues, and model metadata from filesystem to database.

Replaces sync_specimens.py with new snapshot-based schema.
Includes model metadata sync (previously in sync_model_metadata.py).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
import yaml

from adgn.openai_utils.model_metadata import MODEL_METADATA
from adgn.props.db import get_session
from adgn.props.db.models import (
    AgentDefinition,
    FalsePositive,
    FalsePositiveOccurrenceORM,
    FileSet,
    FileSetMember,
    ModelMetadata,
    OccurrenceTrigger,
    Snapshot,
    SnapshotFile,
    TruePositive,
    TruePositiveOccurrenceORM,
)
from adgn.props.definition_utils import pack_definition, validate_packed_definition
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.snapshot import SnapshotDoc
from adgn.props.prop_utils import specimens_definitions_root

from ._loader import FilesystemLoader

# Agent definitions are stored in the props package under agent_defs/
AGENT_DEFS_PATH = Path(__file__).parent.parent.parent / "agent_defs"

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

    For each snapshot, loads issues from specimens/{slug}/issues/*.yaml
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
                # New issue - create ORM instance and occurrences
                logger.debug(f"Adding issue: {issue.snapshot_slug}/{issue.tp_id}")
                orm_issue = TruePositive(
                    snapshot_slug=issue.snapshot_slug, tp_id=issue.tp_id, rationale=issue.rationale
                )
                session.add(orm_issue)
                # Add occurrences to normalized table
                for occ in issue.occurrences:
                    orm_occ = TruePositiveOccurrenceORM(
                        snapshot_slug=issue.snapshot_slug,
                        tp_id=issue.tp_id,
                        occurrence_id=occ.occurrence_id,
                        files={
                            str(p): [lr.model_dump() if lr else None for lr in ranges] if ranges else None
                            for p, ranges in occ.files.items()
                        },
                        note=occ.note,
                        expect_caught_from=[[str(p) for p in fs] for fs in occ.expect_caught_from],
                    )
                    session.add(orm_occ)
                added += 1
                total += 1
            else:
                # Existing issue - check if update needed
                existing = existing_issues[key]
                needs_update = False

                if existing.rationale != issue.rationale:
                    logger.debug(f"Updating issue rationale: {key}")
                    needs_update = True

                # For now, always update occurrences if any change detected
                # TODO: Implement proper occurrence comparison
                if needs_update:
                    existing.rationale = issue.rationale
                    # Delete existing occurrences and re-add (cascade handles this)
                    for occ_orm in list(existing.occurrences):
                        session.delete(occ_orm)
                    for occ in issue.occurrences:
                        orm_occ = TruePositiveOccurrenceORM(
                            snapshot_slug=issue.snapshot_slug,
                            tp_id=issue.tp_id,
                            occurrence_id=occ.occurrence_id,
                            files={
                                str(p): [lr.model_dump() if lr else None for lr in ranges] if ranges else None
                                for p, ranges in occ.files.items()
                            },
                            note=occ.note,
                            expect_caught_from=[[str(p) for p in fs] for fs in occ.expect_caught_from],
                        )
                        session.add(orm_occ)
                    updated += 1
                    total += 1
                else:
                    total += 1

        # Sync false positives
        for fp in false_positives:
            fp_key = (fp.snapshot_slug, fp.fp_id)
            seen_fp_keys.add(fp_key)

            if fp_key not in existing_fps:
                # New FP - create ORM instance and occurrences
                logger.debug(f"Adding false positive: {fp.snapshot_slug}/{fp.fp_id}")
                orm_fp = FalsePositive(snapshot_slug=fp.snapshot_slug, fp_id=fp.fp_id, rationale=fp.rationale)
                session.add(orm_fp)
                # Add occurrences to normalized table
                for fp_occ in fp.occurrences:
                    fp_orm_occ = FalsePositiveOccurrenceORM(
                        snapshot_slug=fp.snapshot_slug,
                        fp_id=fp.fp_id,
                        occurrence_id=fp_occ.occurrence_id,
                        files={
                            str(p): [lr.model_dump() if lr else None for lr in ranges] if ranges else None
                            for p, ranges in fp_occ.files.items()
                        },
                        note=fp_occ.note,
                        relevant_files=[str(p) for p in fp_occ.relevant_files],
                    )
                    session.add(fp_orm_occ)
                added += 1
                total += 1
            else:
                # Existing FP - check if update needed
                existing_fp = existing_fps[fp_key]
                fp_needs_update = False

                if existing_fp.rationale != fp.rationale:
                    logger.debug(f"Updating FP rationale: {fp_key}")
                    fp_needs_update = True

                # For now, always update occurrences if any change detected
                # TODO: Implement proper occurrence comparison
                if fp_needs_update:
                    existing_fp.rationale = fp.rationale
                    # Delete existing occurrences and re-add (cascade handles this)
                    for fp_occ_orm in list(existing_fp.occurrences):
                        session.delete(fp_occ_orm)
                    for fp_occ in fp.occurrences:
                        fp_orm_occ = FalsePositiveOccurrenceORM(
                            snapshot_slug=fp.snapshot_slug,
                            fp_id=fp.fp_id,
                            occurrence_id=fp_occ.occurrence_id,
                            files={
                                str(p): [lr.model_dump() if lr else None for lr in ranges] if ranges else None
                                for p, ranges in fp_occ.files.items()
                            },
                            note=fp_occ.note,
                            relevant_files=[str(p) for p in fp_occ.relevant_files],
                        )
                        session.add(fp_orm_occ)
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


async def sync_snapshot_files_to_db(session: Session, base_path: Path, hydrator: SnapshotHydrator) -> SyncStats:
    """Sync snapshot_files table from hydrated snapshot content.

    Populates snapshot_files with all files in each snapshot for FK validation.

    Args:
        session: SQLAlchemy session
        base_path: Specimens base directory (used to load snapshot manifests)
        hydrator: SnapshotHydrator instance for extracting source code

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """
    manifests = load_manifests_from_yaml(base_path)

    # Get existing files from DB
    existing_by_key = {(sf.snapshot_slug, sf.relative_path): sf for sf in session.query(SnapshotFile).all()}
    seen_keys: set[tuple[SnapshotSlug, str]] = set()

    total = 0
    added = 0
    updated = 0
    deleted = 0

    for slug, _manifest in manifests.items():
        # Hydrate snapshot to get file listing
        async with hydrator.hydrate(slug) as hydrated:
            for file_path in hydrated.content_root.rglob("*"):
                if not file_path.is_file():
                    continue

                relative = str(file_path.relative_to(hydrated.content_root))
                key = (slug, relative)
                seen_keys.add(key)

                # Count lines (errors="replace" handles encoding issues, let other errors crash)
                content = file_path.read_text(encoding="utf-8", errors="replace")
                line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

                if key not in existing_by_key:
                    session.add(SnapshotFile(snapshot_slug=slug, relative_path=relative, line_count=line_count))
                    added += 1
                else:
                    existing = existing_by_key[key]
                    if existing.line_count != line_count:
                        existing.line_count = line_count
                        updated += 1

                total += 1

    # Delete orphaned files
    for key in set(existing_by_key.keys()) - seen_keys:
        session.delete(existing_by_key[key])
        deleted += 1

    session.commit()
    logger.info(f"Snapshot files synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={total} total")
    return SyncStats(total=total, added=added, updated=updated, deleted=deleted)


def _compute_files_hash(file_paths: list[str]) -> str:
    """Compute content-addressable hash for a file set.

    Args:
        file_paths: List of relative file paths

    Returns:
        MD5 hash of sorted, newline-joined file paths
    """
    import hashlib

    sorted_paths = sorted(file_paths)
    content = "\n".join(sorted_paths)
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def sync_file_sets_to_db(session: Session, base_path: Path) -> SyncStats:
    """Sync file_sets, file_set_members, and occurrence_triggers from true_positives.expect_caught_from.

    Populates content-addressable file sets from JSONB expect_caught_from data.
    Examples are derived automatically via the examples VIEW.

    The file_sets table uses (snapshot_slug, files_hash) as primary key where
    files_hash is the MD5 hash of sorted file paths - content-addressable.

    Args:
        session: SQLAlchemy session
        base_path: Specimens base directory (used to load snapshot manifests)

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """
    manifests = load_manifests_from_yaml(base_path)

    # Delete all existing file sets (simpler than incremental update)
    # CASCADE will delete file_set_members and occurrence_triggers
    deleted_file_sets = session.query(FileSet).delete()
    deleted_occurrence_triggers = session.query(OccurrenceTrigger).delete()
    session.flush()

    file_sets_added = 0
    occurrence_triggers_added = 0

    # Track created file sets to avoid duplicates within same snapshot
    created_file_sets: set[tuple[SnapshotSlug, str]] = set()

    for slug in manifests:
        snapshot = session.query(Snapshot).filter_by(slug=slug).one()

        for tp in snapshot.true_positives:
            for occurrence in tp.occurrences:
                for trigger_files in occurrence.expect_caught_from:
                    # Convert to strings and compute hash
                    file_paths = [str(f) for f in trigger_files]
                    files_hash = _compute_files_hash(file_paths)

                    # Create file set if not already exists for this snapshot
                    file_set_key = (slug, files_hash)
                    if file_set_key not in created_file_sets:
                        file_set = FileSet(snapshot_slug=slug, files_hash=files_hash)
                        session.add(file_set)
                        session.flush()

                        # Add file members
                        for file_path in file_paths:
                            member = FileSetMember(snapshot_slug=slug, files_hash=files_hash, file_path=file_path)
                            session.add(member)

                        created_file_sets.add(file_set_key)
                        file_sets_added += 1

                    # Create occurrence trigger linking occurrence to file set
                    occurrence_trigger = OccurrenceTrigger(
                        snapshot_slug=slug,
                        tp_id=tp.tp_id,
                        occurrence_id=occurrence.occurrence_id,
                        files_hash=files_hash,
                    )
                    session.add(occurrence_trigger)
                    occurrence_triggers_added += 1

    session.commit()
    logger.info(
        f"File sets synced: +{file_sets_added} file_sets added, "
        f"+{occurrence_triggers_added} occurrence_triggers added, "
        f"-{deleted_file_sets} file_sets deleted, -{deleted_occurrence_triggers} occurrence_triggers deleted"
    )
    return SyncStats(total=file_sets_added, added=file_sets_added, updated=0, deleted=deleted_file_sets)


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


# ============================================================================
# Agent Definitions Sync (from repo-tracked agent_defs/)
# ============================================================================


# Detector definitions that inherit from critic (use critic agent_type)
CRITIC_BASED_DETECTORS = {"dead_code", "flag_propagation", "contract_truthfulness", "high_recall_critic"}


def sync_agent_definitions_to_db(session: Session) -> SyncStats:
    """Sync repo-tracked agent definitions from agent_defs/ to database.

    Reads agent definitions from src/adgn/props/agent_defs/ directory.
    Each subdirectory is an agent type (e.g., critic/, grader/).
    Definition ID is the directory name.

    Symlinks are resolved at pack time: if a definition has symlinks to files
    or directories outside the definition, they are resolved and their content
    is included in the packed archive. This allows definitions to share common
    files (e.g., docs/, examples/) via symlinks without hardcoded layering.

    Args:
        session: SQLAlchemy session

    Returns:
        Statistics about what changed (total, added, updated, deleted)
    """
    if not AGENT_DEFS_PATH.exists():
        logger.warning(f"Agent definitions directory not found: {AGENT_DEFS_PATH}")
        return SyncStats(total=0, added=0, updated=0, deleted=0)

    # Find all definition directories (immediate children of agent_defs/, excluding common and __pycache__)
    definition_dirs = [
        d
        for d in AGENT_DEFS_PATH.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in ("common", "__pycache__")
    ]

    # Get existing definitions from DB (only repo-backed ones - no created_by_agent_run_id)
    existing = {
        d.id: d for d in session.query(AgentDefinition).filter(AgentDefinition.created_by_agent_run_id.is_(None)).all()
    }
    source_ids = {d.name for d in definition_dirs}
    db_ids = set(existing.keys())

    # Track stats
    added = 0
    updated = 0
    deleted = 0

    # Delete orphaned definitions (in DB but not in source)
    for def_id in db_ids - source_ids:
        logger.info(f"Deleting orphaned agent definition: {def_id}")
        session.delete(existing[def_id])
        deleted += 1

    # Add/update definitions from source
    for definition_dir in definition_dirs:
        def_id = definition_dir.name

        # Pack archive (symlinks to external content are resolved automatically)
        archive = pack_definition(definition_dir)

        # Validate the packed archive - fail hard on invalid definitions
        errors = validate_packed_definition(archive)
        if errors:
            raise ValueError(f"Invalid agent definition '{def_id}': {errors}")

        # Critic-based detectors use "critic" as their agent_type (run with critic infra)
        agent_type = "critic" if def_id in CRITIC_BASED_DETECTORS else def_id

        if def_id not in db_ids:
            # New definition - insert
            logger.info(f"Adding agent definition: {def_id} (type={agent_type})")
            definition = AgentDefinition(
                id=def_id,
                agent_type=agent_type,
                archive=archive,
                created_by_agent_run_id=None,  # Repo-backed
            )
            session.add(definition)
            added += 1
        else:
            # Existing repo-backed definition - always update (cheap operation)
            existing_def = existing[def_id]
            logger.debug(f"Updating agent definition: {def_id} (type={agent_type})")
            existing_def.archive = archive
            existing_def.agent_type = agent_type
            updated += 1

    session.commit()
    total = len(definition_dirs)
    logger.info(f"Agent definitions synced: +{added} added, ~{updated} updated, -{deleted} deleted, ={total} total")
    return SyncStats(total=total, added=added, updated=updated, deleted=deleted)
