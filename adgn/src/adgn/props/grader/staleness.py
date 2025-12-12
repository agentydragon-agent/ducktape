"""Utilities for detecting stale grader runs."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import canonicaljson
from sqlalchemy import select

from adgn.props.db import get_session
from adgn.props.db.models import (
    CanonicalIssuesSnapshot,
    CriticRun,
    FalsePositive,
    GraderRun,
    Snapshot as DBSnapshot,
    TruePositive,
)
from adgn.props.db.snapshots import (
    DBFalsePositiveOccurrence,
    DBKnownFalsePositive,
    DBLineRange,
    DBTruePositiveIssue,
    DBTruePositiveOccurrence,
)
from adgn.props.ids import SnapshotSlug


def _orm_tp_to_db(orm_tp: TruePositive) -> DBTruePositiveIssue:
    """Convert ORM TruePositive to DB persistence model."""
    return DBTruePositiveIssue(
        id=orm_tp.tp_id,
        rationale=orm_tp.rationale,
        occurrences=[
            DBTruePositiveOccurrence(
                files={
                    str(path): (
                        [DBLineRange(start_line=lr.start_line, end_line=lr.end_line) for lr in ranges]
                        if ranges
                        else None
                    )
                    for path, ranges in occ.files.items()
                },
                note=occ.note,
                expect_caught_from=[[str(p) for p in trigger_set] for trigger_set in occ.expect_caught_from],
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
                files={
                    str(path): (
                        [DBLineRange(start_line=lr.start_line, end_line=lr.end_line) for lr in ranges]
                        if ranges
                        else None
                    )
                    for path, ranges in occ.files.items()
                },
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
            for trigger_set in occurrence.expect_caught_from
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


def load_current_canonical_issues_from_db(snapshot_slug: SnapshotSlug, targeted_files: set[Path]) -> dict[str, Any]:
    """Load current canonical TPs+FPs from database, filtered to targeted_files."""
    with get_session() as session:
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


def check_staleness() -> tuple[int, int, dict[SnapshotSlug, dict[str, int]]]:
    """Check for stale grader runs by comparing stored canonical snapshots with current issues.

    Returns:
        Tuple of (total_runs, stale_runs, by_snapshot_stats)

    Note: All grader runs now have canonical_issues_snapshot (NOT NULL constraint enforced).
    Legacy runs without snapshots were cleaned up in Dec 2025.
    """
    total = 0
    stale = 0
    by_snapshot: dict[SnapshotSlug, dict[str, int]] = defaultdict(lambda: {"total": 0, "stale": 0})
    current_canonical_cache: dict[tuple[SnapshotSlug, frozenset[str]], dict[str, Any]] = {}

    with get_session() as session:
        # Query GraderRun with CriticRun for files (no Event join needed)
        query = (
            select(GraderRun.snapshot_slug, GraderRun.canonical_issues_snapshot, CriticRun.files)
            .join(CriticRun, CriticRun.critique_id == GraderRun.critique_id)
            .order_by(GraderRun.created_at.desc())
        )

        for snapshot_slug, stored_snapshot, critic_files in session.execute(query):
            total += 1
            by_snapshot[snapshot_slug]["total"] += 1

            # All grader runs must have canonical_issues_snapshot (enforced by NOT NULL constraint)
            # This assertion documents the database invariant
            assert stored_snapshot is not None, f"Grader run {snapshot_slug} missing canonical_issues_snapshot"

            targeted_files = {Path(f) for f in critic_files}

            # Filter stored snapshot to only catchable TPs and relevant FPs (same filtering applied at grading time)
            catchable_stored_tps = filter_catchable_db_tps(stored_snapshot.true_positives, targeted_files)
            relevant_stored_fps = filter_relevant_db_fps(stored_snapshot.false_positives, targeted_files)

            # Create filtered snapshot model and serialize
            filtered_stored = CanonicalIssuesSnapshot(
                true_positives=catchable_stored_tps, false_positives=relevant_stored_fps
            )
            stored_canonical = filtered_stored.model_dump(mode="json")

            # Load current canonical issues (cached by snapshot+files)
            cache_key = (snapshot_slug, frozenset(critic_files))
            if cache_key not in current_canonical_cache:
                current_canonical_cache[cache_key] = load_current_canonical_issues_from_db(
                    snapshot_slug, targeted_files
                )
            current_canonical = current_canonical_cache[cache_key]

            # Compare canonical JSON representations
            stored_bytes = canonicaljson.encode_canonical_json(stored_canonical)
            current_bytes = canonicaljson.encode_canonical_json(current_canonical)

            if stored_bytes != current_bytes:
                stale += 1
                by_snapshot[snapshot_slug]["stale"] += 1

    return total, stale, by_snapshot
