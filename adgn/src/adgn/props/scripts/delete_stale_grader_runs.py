#!/usr/bin/env python3
"""Delete stale grader runs and their transcripts.

Identifies grader runs where the canonical issues have changed since grading,
then deletes both the grader runs and their associated transcript events.
"""

from __future__ import annotations

import argparse
from uuid import UUID

from adgn.props.db import get_session
from adgn.props.db.models import AgentRun, Event
from adgn.props.grader.staleness import identify_stale_runs


def delete_stale_runs(stale_run_ids: list[UUID], dry_run: bool = False) -> None:
    """Delete stale grader runs and their transcripts.

    Args:
        stale_run_ids: List of grader run UUIDs to delete
        dry_run: If True, only show what would be deleted without actually deleting
    """
    if not stale_run_ids:
        print("No stale runs to delete")
        return

    print(f"\n{'DRY RUN: ' if dry_run else ''}Deleting {len(stale_run_ids)} stale grader runs...")

    with get_session() as session:
        print(f"{'Would delete' if dry_run else 'Deleting'} {len(stale_run_ids)} grader runs and their events")

        if not dry_run:
            # Delete in transaction
            # First delete events (linked directly to agent_run_id)
            deleted_events = (
                session.query(Event).filter(Event.agent_run_id.in_(stale_run_ids)).delete(synchronize_session=False)
            )

            # Then delete agent_runs (graders)
            deleted_runs = (
                session.query(AgentRun)
                .filter(AgentRun.agent_run_id.in_(stale_run_ids))
                .delete(synchronize_session=False)
            )

            session.commit()
            print(f"✓ Deleted {deleted_runs} agent runs and {deleted_events} events")


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
