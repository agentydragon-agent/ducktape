#!/usr/bin/env python3
"""Example clustering queries with auto-detected run_id.

This script demonstrates how to query clustering tables as a scoped agent.
It auto-detects the run_id from the current PostgreSQL username and provides
executable examples for common operations.

Usage:
    # Show current run info
    python example_queries.py show-run-info

    # List all clusters
    python example_queries.py list-clusters

    # List active assignments
    python example_queries.py list-assignments

    # Show unassigned unknowns
    python example_queries.py list-unassigned

    # Show assignment for specific unknown
    python example_queries.py show-assignment <grader_run_id> <unknown_id>
"""

from __future__ import annotations

import sys
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from adgn.props.db import get_session
from adgn.props.db.clustering_models import ClusteringRun, UnknownAssignment, UnknownCluster
from adgn.props.db.models import GraderRun, GraderRunStatus, GradingDecision, ReportedIssue
from adgn.props.ids import SnapshotSlug


def get_current_run_id(session: Session) -> int | None:
    """Extract run_id from the current PostgreSQL username.

    Expected pattern: clustering_run_{run_id}_agent

    Returns:
        Run ID as integer, or None if username doesn't match pattern
    """
    result = session.execute(text("SELECT current_clustering_run_id()"))
    return result.scalar()


def show_run_info(session: Session) -> None:
    """Display information about the current clustering run."""
    run_id = get_current_run_id(session)
    if run_id is None:
        print("ERROR: Not running as a clustering agent user")
        print("Expected username pattern: clustering_run_<id>_agent")
        return

    print(f"Current run_id: {run_id}")
    print()

    # Get run details
    run = session.get(ClusteringRun, run_id)
    if run is None:
        print(f"ERROR: Run {run_id} not found (RLS might be blocking access)")
        return

    print(f"Snapshot: {run.snapshot_slug}")
    print(f"Status: {run.status}")
    print(f"Started: {run.started_at}")
    print(f"Completed: {run.completed_at or 'N/A'}")
    if run.transcript_id:
        print(f"Transcript ID: {run.transcript_id}")


def list_clusters(session: Session) -> None:
    """List all clusters for the current run."""
    clusters = session.execute(select(UnknownCluster).order_by(UnknownCluster.cluster_name)).scalars().all()

    if not clusters:
        print("No clusters created yet")
        return

    print(f"Found {len(clusters)} cluster(s):")
    print()
    for cluster in clusters:
        # Count active assignments to this cluster
        assignment_count = (
            session.execute(
                select(UnknownAssignment).where(
                    UnknownAssignment.cluster_id == cluster.id, UnknownAssignment.cancelled_at.is_(None)
                )
            )
            .scalars()
            .all()
        )

        print(f"[{cluster.id}] {cluster.cluster_name}")
        print(f"    Description: {cluster.description}")
        print(f"    Active assignments: {len(assignment_count)}")
        print(f"    Created: {cluster.created_at}")
        print()


def list_assignments(session: Session, show_cancelled: bool = False) -> None:
    """List assignments for the current run.

    Args:
        show_cancelled: If True, include cancelled assignments
    """
    query = select(UnknownAssignment).order_by(UnknownAssignment.created_at)

    if not show_cancelled:
        query = query.where(UnknownAssignment.cancelled_at.is_(None))

    assignments = session.execute(query).scalars().all()

    if not assignments:
        status = "active" if not show_cancelled else "any"
        print(f"No {status} assignments found")
        return

    print(f"Found {len(assignments)} assignment(s):")
    print()

    for assignment in assignments:
        status = "CANCELLED" if assignment.cancelled_at else "ACTIVE"
        print(f"[{assignment.id}] {status}")
        print(f"    Unknown: grader_run={assignment.grader_run_id}, id={assignment.unknown_id}")

        # Show target
        if assignment.cluster_id:
            cluster = session.get(UnknownCluster, assignment.cluster_id)
            cluster_name = cluster.cluster_name if cluster else "?"
            print(f"    Target: cluster '{cluster_name}' (id={assignment.cluster_id})")
        elif assignment.mapped_tp_id:
            print(f"    Target: TP '{assignment.mapped_tp_id}'")
        elif assignment.mapped_fp_id:
            print(f"    Target: FP '{assignment.mapped_fp_id}'")

        print(f"    Rationale: {assignment.rationale}")
        print(f"    Created: {assignment.created_at}")

        if assignment.cancelled_at:
            print(f"    Cancelled: {assignment.cancelled_at}")
            if assignment.cancellation_reason:
                print(f"    Cancellation reason: {assignment.cancellation_reason}")

        print()


def list_unassigned(session: Session, snapshot_slug: SnapshotSlug) -> None:
    """Show unknowns from grader runs that haven't been assigned yet.

    This demonstrates how to join with reference tables (grader_runs) to find
    unknowns that need clustering.
    """
    # Get all completed grader runs for this snapshot
    grader_runs = (
        session.execute(
            select(GraderRun).where(
                GraderRun.snapshot_slug == snapshot_slug, GraderRun.status == GraderRunStatus.COMPLETED
            )
        )
        .scalars()
        .all()
    )

    if not grader_runs:
        print(f"No completed grader runs found for snapshot {snapshot_slug}")
        return

    print(f"Checking {len(grader_runs)} grader run(s) for unassigned unknowns...")
    print()

    total_unassigned = 0

    for gr in grader_runs:
        # Query grading decisions with no TP match (unknowns)
        unknown_decisions = (
            session.execute(
                select(GradingDecision).where(
                    GradingDecision.grader_run_id == gr.id, GradingDecision.target_tp_id.is_(None)
                )
            )
            .scalars()
            .all()
        )

        if not unknown_decisions:
            continue

        # Check which ones are unassigned
        unassigned = []
        for decision in unknown_decisions:
            unknown_id = decision.input_issue_id
            if not unknown_id:
                continue

            # Check if assigned (active, non-cancelled)
            existing = session.execute(
                select(UnknownAssignment).where(
                    UnknownAssignment.grader_run_id == gr.id,
                    UnknownAssignment.unknown_id == unknown_id,
                    UnknownAssignment.cancelled_at.is_(None),
                )
            ).scalar_one_or_none()

            if existing is None:
                # Load reported issue to get rationale
                reported_issue = session.execute(
                    select(ReportedIssue).where(
                        ReportedIssue.critic_run_id == gr.critic_run_id, ReportedIssue.issue_id == unknown_id
                    )
                ).scalar_one_or_none()

                unassigned.append((decision, reported_issue))

        if unassigned:
            print(f"Grader run {gr.id}:")
            print(f"  Total unknowns: {len(unknown_decisions)}")
            print(f"  Unassigned: {len(unassigned)}")
            print()
            for decision, reported_issue in unassigned[:3]:  # Show first 3
                print(f"  - {decision.input_issue_id}")
                if reported_issue and reported_issue.rationale:
                    print(f"    {reported_issue.rationale[:80]}...")
            if len(unassigned) > 3:
                print(f"  ... and {len(unassigned) - 3} more")
            print()
            total_unassigned += len(unassigned)

    if total_unassigned == 0:
        print("All unknowns have been assigned!")
    else:
        print(f"Total unassigned unknowns: {total_unassigned}")


def show_assignment(session: Session, grader_run_id: UUID, unknown_id: str) -> None:
    """Show the current active assignment for a specific unknown."""
    assignment = session.execute(
        select(UnknownAssignment).where(
            UnknownAssignment.grader_run_id == grader_run_id,
            UnknownAssignment.unknown_id == unknown_id,
            UnknownAssignment.cancelled_at.is_(None),
        )
    ).scalar_one_or_none()

    if assignment is None:
        print(f"No active assignment found for unknown {unknown_id} in grader run {grader_run_id}")
        return

    print(f"Assignment [{assignment.id}]:")
    print(f"  Clustering run: {assignment.clustering_run_id}")
    print(f"  Unknown: grader_run={assignment.grader_run_id}, id={assignment.unknown_id}")

    # Show target details
    if assignment.cluster_id:
        cluster = session.get(UnknownCluster, assignment.cluster_id)
        if cluster:
            print(f"  Target: Cluster '{cluster.cluster_name}'")
            print(f"  Cluster description: {cluster.description}")
    elif assignment.mapped_tp_id:
        print(f"  Target: True Positive '{assignment.mapped_tp_id}'")
    elif assignment.mapped_fp_id:
        print(f"  Target: False Positive '{assignment.mapped_fp_id}'")

    print(f"  Rationale: {assignment.rationale}")
    print(f"  Created: {assignment.created_at}")


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    # Connect to database using get_session() which auto-initializes from PG* env vars.
    # When running as a scoped agent, those vars will be set to scoped user credentials.
    with get_session() as session:
        if command == "show-run-info":
            show_run_info(session)

        elif command == "list-clusters":
            list_clusters(session)

        elif command == "list-assignments":
            show_cancelled = "--all" in sys.argv
            list_assignments(session, show_cancelled=show_cancelled)

        elif command == "list-unassigned":
            if len(sys.argv) < 3:
                print("Usage: example_queries.py list-unassigned <snapshot_slug>")
                sys.exit(1)
            snapshot_slug = SnapshotSlug(sys.argv[2])
            list_unassigned(session, snapshot_slug)

        elif command == "show-assignment":
            if len(sys.argv) < 4:
                print("Usage: example_queries.py show-assignment <grader_run_id> <unknown_id>")
                sys.exit(1)
            grader_run_id = UUID(sys.argv[2])
            unknown_id = sys.argv[3]
            show_assignment(session, grader_run_id, unknown_id)

        else:
            print(f"Unknown command: {command}")
            print(__doc__)
            sys.exit(1)


if __name__ == "__main__":
    main()
