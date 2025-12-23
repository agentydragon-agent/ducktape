"""Helper functions for clustering operations.

These helpers simplify the clustering workflow by providing typed interfaces
for creating clusters, assigning unknowns, and managing the clustering run.

Database session is obtained automatically using get_session() which respects
the clustering agent's RLS-scoped credentials. The agent_run_id is automatically
fetched via the unified current_agent_run_id() database function.

Typical workflow:
    1. Call create_cluster() for each new cluster category
    2. Call assign_to_cluster() or assign_to_existing() for each unknown
    3. Clustering auto-completes when all unknowns are assigned (no explicit submit)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text

from adgn.props.db import get_session
from adgn.props.db.clustering_models import UnknownAssignment, UnknownCluster


def _get_current_agent_run_id(session) -> UUID:
    """Get the current agent run ID from the database.

    Uses the unified PostgreSQL current_agent_run_id() function which extracts
    the ID from the database username (agent_{run_id} pattern).

    Args:
        session: Active SQLAlchemy session

    Returns:
        UUID of the current agent run

    Raises:
        RuntimeError: If not connected as agent
    """
    result = session.execute(text("SELECT current_agent_run_id()"))
    agent_run_id = result.scalar()
    if agent_run_id is None:
        raise RuntimeError("Not connected as agent (current_agent_run_id() returned NULL)")
    # PostgreSQL returns UUID as string, convert to Python UUID
    if isinstance(agent_run_id, str):
        return UUID(agent_run_id)
    return UUID(str(agent_run_id))


def create_cluster(cluster_name: str, description: str) -> int:
    """Create a new cluster for grouping unknown issues.

    Args:
        cluster_name: Unique kebab-case name for the cluster (e.g., "unused-imports")
        description: Human-readable description of what this cluster represents

    Returns:
        The ID of the newly created cluster

    Example:
        from helpers import create_cluster

        cluster_id = create_cluster(
            cluster_name="unused-imports",
            description="Unused imports that add no value to the codebase"
        )
        print(f"Created cluster with ID: {cluster_id}")

    Note:
        The agent_run_id is automatically fetched from the database using
        current_agent_run_id(). You must be connected as an agent user (agent_{run_id}).
    """
    with get_session() as session:
        agent_run_id = _get_current_agent_run_id(session)
        cluster = UnknownCluster(agent_run_id=agent_run_id, cluster_name=cluster_name, description=description)
        session.add(cluster)
        session.flush()  # Get the ID
        return cluster.id


def assign_to_cluster(grader_run_id: str, unknown_id: str, cluster_name: str, rationale: str) -> None:
    """Assign an unknown issue to a cluster.

    Args:
        grader_run_id: UUID of the grader run that produced this unknown
        unknown_id: ID of the unknown issue (from grading_decisions.input_issue_id)
        cluster_name: Name of the cluster to assign to
        rationale: Explanation for this assignment

    Example:
        from helpers import create_cluster, assign_to_cluster

        # Create cluster first
        create_cluster("unused-imports", "Unused imports that add no value")

        # Then assign unknowns to it
        assign_to_cluster(
            grader_run_id="12345678-1234-...",
            unknown_id="input-issue-5",
            cluster_name="unused-imports",
            rationale="Unused import of typing.cast in utils.py:15"
        )

    Note:
        The cluster must exist for this run. Create it first with create_cluster().
    """
    with get_session() as session:
        agent_run_id = _get_current_agent_run_id(session)

        # Look up cluster by name
        cluster = session.execute(
            select(UnknownCluster).where(
                UnknownCluster.agent_run_id == agent_run_id, UnknownCluster.cluster_name == cluster_name
            )
        ).scalar_one_or_none()

        if cluster is None:
            raise ValueError(f"Cluster '{cluster_name}' not found for this run. Create it first with create_cluster().")

        assignment = UnknownAssignment(
            agent_run_id=agent_run_id,
            grader_run_id=UUID(grader_run_id),
            unknown_id=unknown_id,
            cluster_id=cluster.id,
            rationale=rationale,
        )
        session.add(assignment)


def assign_to_existing_tp(grader_run_id: str, unknown_id: str, tp_id: str, rationale: str) -> None:
    """Assign an unknown issue to an existing True Positive.

    Use this when an unknown should have been matched to an existing TP
    but wasn't caught by the grader.

    Args:
        grader_run_id: UUID of the grader run that produced this unknown
        unknown_id: ID of the unknown issue (from grading_decisions.input_issue_id)
        tp_id: ID of the existing true positive to map to
        rationale: Explanation for this assignment

    Example:
        from helpers import assign_to_existing_tp

        assign_to_existing_tp(
            grader_run_id="12345678-1234-...",
            unknown_id="input-issue-10",
            tp_id="dead-code-utils",
            rationale="This is the same dead code issue as TP dead-code-utils"
        )
    """
    with get_session() as session:
        agent_run_id = _get_current_agent_run_id(session)

        assignment = UnknownAssignment(
            agent_run_id=agent_run_id,
            grader_run_id=UUID(grader_run_id),
            unknown_id=unknown_id,
            mapped_tp_id=tp_id,
            rationale=rationale,
        )
        session.add(assignment)


def assign_to_existing_fp(grader_run_id: str, unknown_id: str, fp_id: str, rationale: str) -> None:
    """Assign an unknown issue to an existing False Positive.

    Use this when an unknown should have been matched to an existing FP
    (known acceptable pattern) but wasn't caught by the grader.

    Args:
        grader_run_id: UUID of the grader run that produced this unknown
        unknown_id: ID of the unknown issue (from grading_decisions.input_issue_id)
        fp_id: ID of the existing false positive to map to
        rationale: Explanation for this assignment

    Example:
        from helpers import assign_to_existing_fp

        assign_to_existing_fp(
            grader_run_id="12345678-1234-...",
            unknown_id="input-issue-15",
            fp_id="acceptable-duplication",
            rationale="This duplication is for visual consistency, same as FP acceptable-duplication"
        )
    """
    with get_session() as session:
        agent_run_id = _get_current_agent_run_id(session)

        assignment = UnknownAssignment(
            agent_run_id=agent_run_id,
            grader_run_id=UUID(grader_run_id),
            unknown_id=unknown_id,
            mapped_fp_id=fp_id,
            rationale=rationale,
        )
        session.add(assignment)


def cancel_assignment(grader_run_id: str, unknown_id: str, cancellation_reason: str) -> None:
    """Cancel an existing assignment (soft delete).

    Use this to undo an incorrect assignment before creating a new one.

    Args:
        grader_run_id: UUID of the grader run
        unknown_id: ID of the unknown issue
        cancellation_reason: Explanation for why this assignment is being cancelled

    Example:
        from helpers import cancel_assignment, assign_to_cluster

        # Cancel incorrect assignment
        cancel_assignment(
            grader_run_id="12345678-1234-...",
            unknown_id="input-issue-5",
            cancellation_reason="Reassigning to different cluster after review"
        )

        # Create new correct assignment
        assign_to_cluster(
            grader_run_id="12345678-1234-...",
            unknown_id="input-issue-5",
            cluster_name="dead-code",
            rationale="Actually dead code, not unused import"
        )
    """
    with get_session() as session:
        agent_run_id = _get_current_agent_run_id(session)

        # Find active assignment
        assignment = session.execute(
            select(UnknownAssignment).where(
                UnknownAssignment.agent_run_id == agent_run_id,
                UnknownAssignment.grader_run_id == UUID(grader_run_id),
                UnknownAssignment.unknown_id == unknown_id,
                UnknownAssignment.cancelled_at.is_(None),
            )
        ).scalar_one_or_none()

        if assignment is None:
            raise ValueError(f"No active assignment found for unknown '{unknown_id}' in grader run '{grader_run_id}'")

        # Soft delete
        assignment.cancelled_at = datetime.now(UTC)
        assignment.cancellation_reason = cancellation_reason
