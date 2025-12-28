"""Utilities for detecting stale grader runs."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

import canonicaljson
from props_core.agent_types import AgentType
from props_core.db.models import (
    AgentRun,
    CanonicalIssuesSnapshot,
    FalsePositive,
    FileSet,
    Snapshot as DBSnapshot,
    TruePositive,
)
from props_core.db.session import Session, get_session
from props_core.db.snapshots import (
    DBFalsePositiveOccurrence,
    DBKnownFalsePositive,
    DBLineRange,
    DBTruePositiveIssue,
    DBTruePositiveOccurrence,
)
from props_core.ids import SnapshotSlug
from props_core.models.examples import ExampleSpec, SingleFileSetExample, WholeSnapshotExample


def _convert_orm_files_to_db(files: dict[str, list[dict] | None]) -> dict[str, list[DBLineRange] | None]:
    """Convert ORM JSONB files dict to DB persistence model format.

    ORM stores files as raw JSONB: {path_str: [{start_line: N, end_line: M}, ...] | null}
    DB model expects: {path_str: [DBLineRange, ...] | null}
    """
    return {
        path: [DBLineRange.model_validate(lr) for lr in ranges] if ranges else None for path, ranges in files.items()
    }


def resolve_scope_files(
    snapshot_slug: SnapshotSlug, example_spec: ExampleSpec, session: Session | None = None
) -> set[Path]:
    """Resolve an ExampleSpec to concrete file set.

    Args:
        snapshot_slug: Snapshot identifier (for validation, already in example_spec)
        example_spec: The example specification (discriminated union)
        session: Optional existing session (avoids nested session issues)

    Returns:
        Set of file paths in the scope
    """
    if session is None:
        with get_session() as new_session:
            return resolve_scope_files(snapshot_slug, example_spec, new_session)

    if isinstance(example_spec, WholeSnapshotExample):
        snapshot = session.query(DBSnapshot).filter_by(slug=snapshot_slug).one()
        return snapshot.files_with_issues()
    if isinstance(example_spec, SingleFileSetExample):
        file_set = (
            session.query(FileSet)
            .filter_by(snapshot_slug=example_spec.snapshot_slug, files_hash=example_spec.files_hash)
            .one()
        )
        return {Path(m.file_path) for m in file_set.members}
    raise ValueError(f"Unknown scope type: {type(example_spec)}")


def _orm_tp_to_db(orm_tp: TruePositive) -> DBTruePositiveIssue:
    """Convert ORM TruePositive to DB persistence model."""
    return DBTruePositiveIssue(
        id=orm_tp.tp_id,
        rationale=orm_tp.rationale,
        occurrences=[
            DBTruePositiveOccurrence(
                occurrence_id=occ.occurrence_id,
                files=_convert_orm_files_to_db(occ.files),
                note=occ.note,
                # Derive from M:N relationship (expected_recall_scopes -> file_sets)
                critic_scopes_expected_to_recall=[
                    [str(p) for p in trigger_set] for trigger_set in occ.critic_scopes_expected_to_recall_set
                ],
            )
            for occ in orm_tp.occurrences
        ],
    )


def _orm_fp_to_db(orm_fp: FalsePositive) -> DBKnownFalsePositive:
    """Convert ORM FalsePositive to DB persistence model."""
    return DBKnownFalsePositive(
        id=orm_fp.fp_id,
        rationale=orm_fp.rationale,
        occurrences=[
            DBFalsePositiveOccurrence(
                occurrence_id=occ.occurrence_id,
                files=_convert_orm_files_to_db(occ.files),
                note=occ.note,
                relevant_files=[str(p) for p in occ.relevant_files],
            )
            for occ in orm_fp.occurrences
        ],
    )


def filter_catchable_db_tps(tps: list[DBTruePositiveIssue], targeted_files: set[Path]) -> list[DBTruePositiveIssue]:
    """Filter DB persistence TPs to only those catchable from targeted_files.

    Works on DB persistence models (for filtering stored snapshots in staleness check).
    """
    targeted_files_str = {str(p) for p in targeted_files}

    def is_catchable(tp: DBTruePositiveIssue) -> bool:
        return any(
            set(trigger_set) <= targeted_files_str
            for occurrence in tp.occurrences
            for trigger_set in occurrence.critic_scopes_expected_to_recall
        )

    return [tp for tp in tps if is_catchable(tp)]


def filter_relevant_db_fps(
    fps: list[Any], targeted_files: set[Path]
) -> list[Any]:  # Any because DBKnownFalsePositive not in snapshots.py imports
    """Filter DB persistence FPs to only those relevant to targeted_files.

    Works on DB persistence models (for filtering stored snapshots in staleness check).
    """
    targeted_files_str = {str(p) for p in targeted_files}

    def is_relevant(fp: Any) -> bool:
        return any(bool(set(occ.relevant_files) & targeted_files_str) for occ in fp.occurrences)

    return [fp for fp in fps if is_relevant(fp)]


def load_current_canonical_issues_from_db(
    snapshot_slug: SnapshotSlug, targeted_files: set[Path], session: Session | None = None
) -> dict[str, Any]:
    """Load current canonical TPs+FPs from database, filtered to targeted_files.

    Args:
        snapshot_slug: Snapshot to load issues from
        targeted_files: Files to filter issues by
        session: Optional existing session (avoids nested session issues)
    """
    if session is None:
        with get_session() as new_session:
            return load_current_canonical_issues_from_db(snapshot_slug, targeted_files, new_session)

    snapshot = session.query(DBSnapshot).filter_by(slug=snapshot_slug).one()

    # Convert ORM models to DB persistence models first
    all_db_tps = [_orm_tp_to_db(tp) for tp in snapshot.true_positives]
    all_db_fps = [_orm_fp_to_db(fp) for fp in snapshot.false_positives]

    # Filter DB persistence models (single implementation shared with staleness check)
    catchable_db_tps = filter_catchable_db_tps(all_db_tps, targeted_files)
    relevant_db_fps = filter_relevant_db_fps(all_db_fps, targeted_files)

    # Create snapshot from filtered DB persistence models
    current_snapshot = CanonicalIssuesSnapshot(true_positives=catchable_db_tps, false_positives=relevant_db_fps)
    return current_snapshot.model_dump(mode="json")


def identify_stale_runs() -> tuple[list[UUID], dict[SnapshotSlug, dict[str, int]]]:
    """Identify stale grader runs by comparing stored canonical snapshots with current issues.

    Returns:
        Tuple of (stale_run_ids, by_snapshot_stats)
        - stale_run_ids: List of grader run UUIDs
        - by_snapshot_stats: Dict mapping snapshot_slug -> {"total": N, "stale": M}

    Note: All grader runs now have canonical_issues_snapshot (NOT NULL constraint enforced).
    Legacy runs without snapshots were cleaned up in Dec 2025.
    """
    stale_run_ids: list[UUID] = []
    by_snapshot: dict[SnapshotSlug, dict[str, int]] = defaultdict(lambda: {"total": 0, "stale": 0})
    current_canonical_cache: dict[ExampleSpec, dict[str, Any]] = {}

    with get_session() as session:
        # Two-phase approach: first get grader runs with their linked critic runs
        # Query AgentRun for graders
        grader_runs = (
            session.query(AgentRun)
            .filter(AgentRun.type_config["agent_type"].astext == AgentType.GRADER)
            .order_by(AgentRun.created_at.desc())
            .all()
        )

        for grader_run in grader_runs:
            grader_config = grader_run.grader_config()
            stored_snapshot = grader_config.canonical_issues_snapshot
            graded_critic_run_id = grader_config.graded_agent_run_id

            # Get the critic run to find example specification
            critic_run = session.get(AgentRun, graded_critic_run_id)
            if not critic_run:
                raise ValueError(f"Critic run {graded_critic_run_id} not found for grader {grader_run.agent_run_id}")

            critic_config = critic_run.critic_config()
            example_spec = critic_config.example
            snapshot_slug = example_spec.snapshot_slug

            by_snapshot[snapshot_slug]["total"] += 1

            # All grader runs must have canonical_issues_snapshot (enforced by NOT NULL constraint)
            # This assertion documents the database invariant
            if stored_snapshot is None:
                continue  # Skip runs without canonical snapshot

            # Parse stored snapshot from dict to model
            stored_snapshot_model = CanonicalIssuesSnapshot.model_validate(stored_snapshot)

            # Resolve scope specification to file set (pass session to avoid nested session issues)
            targeted_files = resolve_scope_files(snapshot_slug, example_spec, session)

            # Filter stored snapshot to only catchable TPs and relevant FPs (same filtering applied at grading time)
            catchable_stored_tps = filter_catchable_db_tps(stored_snapshot_model.true_positives, targeted_files)
            relevant_stored_fps = filter_relevant_db_fps(stored_snapshot_model.false_positives, targeted_files)

            # Create filtered snapshot model and serialize
            filtered_stored = CanonicalIssuesSnapshot(
                true_positives=catchable_stored_tps, false_positives=relevant_stored_fps
            )
            stored_canonical = filtered_stored.model_dump(mode="json")

            # Load current canonical issues (cached by example spec, pass session)
            # ExampleSpec is frozen/hashable so we can use it directly as cache key
            if example_spec not in current_canonical_cache:
                current_canonical_cache[example_spec] = load_current_canonical_issues_from_db(
                    snapshot_slug, targeted_files, session
                )
            current_canonical = current_canonical_cache[example_spec]

            # Compare canonical JSON representations
            stored_bytes = canonicaljson.encode_canonical_json(stored_canonical)
            current_bytes = canonicaljson.encode_canonical_json(current_canonical)

            if stored_bytes != current_bytes:
                stale_run_ids.append(grader_run.agent_run_id)
                by_snapshot[snapshot_slug]["stale"] += 1

    return stale_run_ids, by_snapshot
