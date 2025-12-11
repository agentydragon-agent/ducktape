"""Utilities for detecting stale grader runs."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import canonicaljson
from sqlalchemy import select

from adgn.props.db import get_session
from adgn.props.db.models import CanonicalIssuesSnapshot, CriticRun, GraderRun, Snapshot as DBSnapshot
from adgn.props.db.snapshots import DBTruePositiveIssue
from adgn.props.grader.models import FalsePositiveID, KnownFalsePositive, Rationale, TruePositiveID, TruePositiveIssue
from adgn.props.grader.persistence import fp_to_db, tp_to_db
from adgn.props.ids import SnapshotSlug


def filter_catchable_tps(tps: list[TruePositiveIssue], targeted_files: set[Path]) -> list[TruePositiveIssue]:
    """Filter TPs to only those catchable from targeted_files."""
    catchable = []
    for tp in tps:
        is_catchable = False
        for occurrence in tp.occurrences:
            for trigger_set in occurrence.expect_caught_from:
                if trigger_set <= targeted_files:
                    is_catchable = True
                    break
            if is_catchable:
                break
        if is_catchable:
            catchable.append(tp)
    return catchable


def filter_catchable_db_tps(tps: list[DBTruePositiveIssue], targeted_files: set[Path]) -> list[DBTruePositiveIssue]:
    """Filter DB TPs to only those catchable from targeted_files.

    Works directly on DB models without converting to MCP models.
    """
    targeted_files_str = {str(p) for p in targeted_files}

    def is_catchable(tp: DBTruePositiveIssue) -> bool:
        return any(
            set(trigger_set) <= targeted_files_str
            for occurrence in tp.occurrences
            for trigger_set in occurrence.expect_caught_from
        )

    return [tp for tp in tps if is_catchable(tp)]


def load_current_canonical_issues_from_db(snapshot_slug: SnapshotSlug, targeted_files: set[Path]) -> dict[str, Any]:
    """Load current canonical TPs+FPs from database, filtered to targeted_files."""

    def _tp_from_orm(orm_tp) -> TruePositiveIssue:
        return TruePositiveIssue(
            id=TruePositiveID(orm_tp.tp_id), rationale=Rationale(orm_tp.rationale), occurrences=orm_tp.occurrences
        )

    def _fp_from_orm(orm_fp) -> KnownFalsePositive:
        return KnownFalsePositive(
            id=FalsePositiveID(orm_fp.fp_id), rationale=Rationale(orm_fp.rationale), occurrences=orm_fp.occurrences
        )

    with get_session() as session:
        snapshot = session.query(DBSnapshot).filter_by(slug=snapshot_slug).one()
        canonical_tps = [_tp_from_orm(tp) for tp in snapshot.true_positives]
        canonical_fps = [_fp_from_orm(fp) for fp in snapshot.false_positives]
        catchable_tps = filter_catchable_tps(canonical_tps, targeted_files)

        # Convert MCP models to DB models and create snapshot
        current_snapshot = CanonicalIssuesSnapshot(
            true_positives=[tp_to_db(tp) for tp in catchable_tps],
            false_positives=[fp_to_db(fp) for fp in canonical_fps],
        )
        return current_snapshot.model_dump(mode="json")


def check_staleness() -> tuple[int, int, dict[SnapshotSlug, dict[str, int]]]:
    """Check for stale grader runs by comparing stored canonical snapshots with current issues.

    Returns:
        Tuple of (total_runs, stale_runs, by_snapshot_stats)
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

            targeted_files = {Path(f) for f in critic_files}

            # Filter stored snapshot to only catchable TPs (same filtering applied at grading time)
            catchable_stored_tps = filter_catchable_db_tps(stored_snapshot.true_positives, targeted_files)

            # Create filtered snapshot model and serialize
            filtered_stored = CanonicalIssuesSnapshot(
                true_positives=catchable_stored_tps, false_positives=stored_snapshot.false_positives
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
