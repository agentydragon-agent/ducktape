#!/usr/bin/env python3
"""Delete stale grader runs and their transcripts.

Identifies grader runs where the canonical issues have changed since grading,
then deletes both the grader runs and their associated transcript events.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID

import canonicaljson
from pydantic import TypeAdapter
from sqlalchemy import and_, func, select

from adgn.agent.events import UserText
from adgn.props.db import get_session, init_db
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


def identify_stale_runs() -> tuple[list[str], dict[SnapshotSlug, dict[str, int]]]:
    """Identify stale grader runs.

    Returns:
        Tuple of (list of stale grader_run IDs as strings, stats by snapshot)
    """
    init_db()

    stale_run_ids = []
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

        for run_id, snapshot_slug, _transcript_id, payload, critic_files in session.execute(query):
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
                stale_run_ids.append(str(run_id))
                by_snapshot[snapshot_slug]["stale"] += 1

    return stale_run_ids, by_snapshot


def delete_stale_runs(stale_run_ids: list[str], dry_run: bool = False) -> None:
    """Delete stale grader runs and their transcripts.

    Args:
        stale_run_ids: List of grader run UUIDs (as strings) to delete
        dry_run: If True, only show what would be deleted without actually deleting
    """
    if not stale_run_ids:
        print("No stale runs to delete")
        return

    print(f"\n{'DRY RUN: ' if dry_run else ''}Deleting {len(stale_run_ids)} stale grader runs...")

    # Convert string UUIDs to UUID objects
    run_ids_uuid = [UUID(run_id) for run_id in stale_run_ids]

    with get_session() as session:
        # Get transcript IDs for these grader runs using ORM
        transcript_query = select(GraderRun.transcript_id.distinct()).where(GraderRun.id.in_(run_ids_uuid))
        transcript_ids = [row[0] for row in session.execute(transcript_query)]

        print(f"{'Would delete' if dry_run else 'Deleting'} {len(transcript_ids)} associated transcripts")

        if not dry_run:
            # Delete in transaction
            # First delete grader_runs (they reference transcripts via FK)
            deleted_runs = (
                session.query(GraderRun).filter(GraderRun.id.in_(run_ids_uuid)).delete(synchronize_session=False)
            )

            # Then delete events (transcript data)
            deleted_events = (
                session.query(Event).filter(Event.transcript_id.in_(transcript_ids)).delete(synchronize_session=False)
            )

            session.commit()
            print(
                f"✓ Deleted {deleted_runs} grader runs and {deleted_events} events for {len(transcript_ids)} transcripts"
            )


def main():
    parser = argparse.ArgumentParser(description="Delete stale grader runs and their transcripts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without actually deleting")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    print("Identifying stale grader runs...")
    stale_run_ids, by_snapshot = identify_stale_runs()

    if not stale_run_ids:
        print("No stale runs found")
        return

    print("\n" + "=" * 60)
    print("Stale Runs Summary")
    print("=" * 60)
    print(f"Total stale runs: {len(stale_run_ids)}")
    print()
    print("By snapshot:")
    for slug in sorted(by_snapshot.keys()):
        stats = by_snapshot[slug]
        if stats["stale"] > 0:
            print(f"  {slug}: {stats['stale']} stale out of {stats['total']} total")

    if not args.yes and not args.dry_run:
        print("\n" + "=" * 60)
        response = input(f"Delete {len(stale_run_ids)} stale grader runs? [y/N] ")
        if response.lower() != "y":
            print("Aborted")
            return

    delete_stale_runs(stale_run_ids, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
