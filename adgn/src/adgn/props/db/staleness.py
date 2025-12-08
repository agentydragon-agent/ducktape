"""Utilities for detecting stale grader runs."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any

import canonicaljson
from pydantic import TypeAdapter
from sqlalchemy import and_, func, select

from adgn.agent.events import UserText
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Event, GraderRun, Snapshot as DBSnapshot
from adgn.props.grader.models import FalsePositiveID, KnownFalsePositive, Rationale, TruePositiveID, TruePositiveIssue
from adgn.props.ids import SnapshotSlug


def parse_canonical_issues_from_transcript(user_text: str) -> dict[str, Any] | None:
    """Parse canonical TPs and FPs from grader user message."""
    tp_pattern = r"- canonical positives:\s*```json\s*(\[[\s\S]*?\])\s*```"
    tp_match = re.search(tp_pattern, user_text)

    fp_pattern = r"- known false positives:\s*```json\s*(\[[\s\S]*?\])\s*```"
    fp_match = re.search(fp_pattern, user_text)

    if not tp_match:
        if "- known false positives: (none)" in user_text:
            if not tp_match:
                return None
        else:
            return None

    try:
        tp_json = json.loads(tp_match.group(1))
        fp_json = json.loads(fp_match.group(1)) if fp_match else []
        return {"true_positives": tp_json, "false_positives": fp_json}
    except json.JSONDecodeError:
        return None


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
        tp_data = TypeAdapter(list[TruePositiveIssue]).dump_python(catchable_tps, mode="json")
        fp_data = TypeAdapter(list[KnownFalsePositive]).dump_python(canonical_fps, mode="json")
        return {"true_positives": tp_data, "false_positives": fp_data}


def check_staleness() -> tuple[int, int, dict[SnapshotSlug, dict[str, int]]]:
    """Check for stale grader runs.

    Returns:
        Tuple of (total_runs, stale_runs, by_snapshot_stats)
    """
    total = 0
    stale = 0
    by_snapshot: dict[SnapshotSlug, dict[str, int]] = defaultdict(lambda: {"total": 0, "stale": 0})
    current_canonical_cache: dict[tuple[SnapshotSlug, frozenset[str]], dict[str, Any]] = {}

    with get_session() as session:
        # Subquery to find the first user_text event for each transcript
        min_seq_subq = (
            select(Event.transcript_id, func.min(Event.sequence_num).label("min_seq"))
            .where(Event.event_type == "user_text")
            .group_by(Event.transcript_id)
            .subquery()
        )

        # Main query: join GraderRun with Event and CriticRun
        query = (
            select(GraderRun.id, GraderRun.snapshot_slug, GraderRun.transcript_id, Event.payload, CriticRun.files)
            .join(Event, Event.transcript_id == GraderRun.transcript_id)
            .join(CriticRun, CriticRun.critique_id == GraderRun.critique_id)
            .join(
                min_seq_subq,
                and_(min_seq_subq.c.transcript_id == Event.transcript_id, min_seq_subq.c.min_seq == Event.sequence_num),
            )
            .where(Event.event_type == "user_text")
            .order_by(GraderRun.created_at.desc())
        )

        for _run_id, snapshot_slug, _transcript_id, payload, critic_files in session.execute(query):
            total += 1
            by_snapshot[snapshot_slug]["total"] += 1

            # Extract text from the payload (EventType union - should be UserText for user_text events)
            if not isinstance(payload, UserText):
                continue
            user_text = payload.text
            transcript_canonical_json = parse_canonical_issues_from_transcript(user_text)

            if transcript_canonical_json is None:
                continue

            targeted_files = {Path(f) for f in critic_files}

            transcript_tps = TypeAdapter(list[TruePositiveIssue]).validate_python(
                transcript_canonical_json["true_positives"]
            )
            transcript_fps = TypeAdapter(list[KnownFalsePositive]).validate_python(
                transcript_canonical_json["false_positives"]
            )

            catchable_transcript_tps = filter_catchable_tps(transcript_tps, targeted_files)

            transcript_canonical = {
                "true_positives": TypeAdapter(list[TruePositiveIssue]).dump_python(
                    catchable_transcript_tps, mode="json"
                ),
                "false_positives": TypeAdapter(list[KnownFalsePositive]).dump_python(transcript_fps, mode="json"),
            }

            cache_key = (snapshot_slug, frozenset(critic_files))
            if cache_key not in current_canonical_cache:
                current_canonical_cache[cache_key] = load_current_canonical_issues_from_db(
                    snapshot_slug, targeted_files
                )
            current_canonical = current_canonical_cache[cache_key]

            transcript_bytes = canonicaljson.encode_canonical_json(transcript_canonical)
            current_bytes = canonicaljson.encode_canonical_json(current_canonical)

            if transcript_bytes != current_bytes:
                stale += 1
                by_snapshot[snapshot_slug]["stale"] += 1

    return total, stale, by_snapshot
