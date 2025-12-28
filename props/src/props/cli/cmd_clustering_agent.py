"""Clustering agent CLI for categorizing unknown issues.

Commands for creating clusters, assigning unknowns, and managing assignments.
Used by clustering agents running inside containers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated
from uuid import UUID

from sqlalchemy import select, text
import typer

from agent_container_util.output import render_agent_prompt
from props.db.clustering_models import UnknownAssignment, UnknownCluster
from props.db.session import get_session

HELP_TEXT = """Clustering agent commands for categorizing unknown issues.

Common workflows:

  Create a new cluster and assign issues:
    props clustering-agent create-cluster "unused-imports" "Imports with no usage"
    props clustering-agent assign-to-cluster "grader-run-uuid" "issue-5" "unused-imports" "Rationale"

  Link to existing ground truth:
    props clustering-agent assign-to-tp "grader-run-uuid" "issue-10" "dead-code-utils" "Same as TP"
    props clustering-agent assign-to-fp "grader-run-uuid" "issue-15" "acceptable-dup" "Known pattern"

  Correct a mistake:
    props clustering-agent cancel-assignment "grader-run-uuid" "issue-5" "Reassigning"
"""

app = typer.Typer(name="clustering-agent", help=HELP_TEXT, add_completion=False)


def _get_current_agent_run_id(session) -> UUID:
    """Get the current agent run ID from the database."""
    result = session.execute(text("SELECT current_agent_run_id()"))
    agent_run_id = result.scalar()
    if agent_run_id is None:
        raise RuntimeError("Not connected as agent (current_agent_run_id() returned NULL)")
    if isinstance(agent_run_id, str):
        return UUID(agent_run_id)
    return UUID(str(agent_run_id))


@app.command("create-cluster")
def create_cluster_cmd(
    cluster_name: Annotated[str, typer.Argument(help="Kebab-case cluster name (e.g., 'unused-imports')")],
    description: Annotated[str, typer.Argument(help="Description of what this cluster represents")],
) -> None:
    """Create a new cluster for grouping unknown issues."""
    start = perf_counter()
    with get_session() as session:
        agent_run_id = _get_current_agent_run_id(session)
        cluster = UnknownCluster(agent_run_id=agent_run_id, cluster_name=cluster_name, description=description)
        session.add(cluster)
        session.flush()
        cluster_id = cluster.id
    elapsed = perf_counter() - start
    typer.echo(f"Created cluster '{cluster_name}' with ID: {cluster_id} (elapsed={elapsed:.3f}s)")


@app.command("assign-to-cluster")
def assign_to_cluster_cmd(
    grader_run_id: Annotated[str, typer.Argument(help="UUID of the grader run")],
    unknown_id: Annotated[str, typer.Argument(help="ID of the unknown issue")],
    cluster_name: Annotated[str, typer.Argument(help="Name of the cluster to assign to")],
    rationale: Annotated[str, typer.Argument(help="Explanation for this assignment")],
) -> None:
    """Assign an unknown issue to a cluster."""
    start = perf_counter()
    with get_session() as session:
        agent_run_id = _get_current_agent_run_id(session)

        cluster = session.execute(
            select(UnknownCluster).where(
                UnknownCluster.agent_run_id == agent_run_id, UnknownCluster.cluster_name == cluster_name
            )
        ).scalar_one_or_none()

        if cluster is None:
            typer.echo(f"Error: Cluster '{cluster_name}' not found. Create it first with create-cluster.", err=True)
            raise typer.Exit(1)

        assignment = UnknownAssignment(
            agent_run_id=agent_run_id,
            grader_run_id=UUID(grader_run_id),
            unknown_id=unknown_id,
            cluster_id=cluster.id,
            rationale=rationale,
        )
        session.add(assignment)

    elapsed = perf_counter() - start
    typer.echo(f"Assigned {unknown_id} to cluster '{cluster_name}' (elapsed={elapsed:.3f}s)")


@app.command("assign-to-tp")
def assign_to_tp_cmd(
    grader_run_id: Annotated[str, typer.Argument(help="UUID of the grader run")],
    unknown_id: Annotated[str, typer.Argument(help="ID of the unknown issue")],
    tp_id: Annotated[str, typer.Argument(help="ID of the existing true positive")],
    rationale: Annotated[str, typer.Argument(help="Explanation for this assignment")],
) -> None:
    """Assign an unknown issue to an existing True Positive."""
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

    typer.echo(f"Assigned {unknown_id} to existing TP '{tp_id}'")


@app.command("assign-to-fp")
def assign_to_fp_cmd(
    grader_run_id: Annotated[str, typer.Argument(help="UUID of the grader run")],
    unknown_id: Annotated[str, typer.Argument(help="ID of the unknown issue")],
    fp_id: Annotated[str, typer.Argument(help="ID of the existing false positive")],
    rationale: Annotated[str, typer.Argument(help="Explanation for this assignment")],
) -> None:
    """Assign an unknown issue to an existing False Positive."""
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

    typer.echo(f"Assigned {unknown_id} to existing FP '{fp_id}'")


@app.command("cancel-assignment")
def cancel_assignment_cmd(
    grader_run_id: Annotated[str, typer.Argument(help="UUID of the grader run")],
    unknown_id: Annotated[str, typer.Argument(help="ID of the unknown issue")],
    reason: Annotated[str, typer.Argument(help="Reason for cancelling the assignment")],
) -> None:
    """Cancel an existing assignment (soft delete)."""
    with get_session() as session:
        agent_run_id = _get_current_agent_run_id(session)

        assignment = session.execute(
            select(UnknownAssignment).where(
                UnknownAssignment.agent_run_id == agent_run_id,
                UnknownAssignment.grader_run_id == UUID(grader_run_id),
                UnknownAssignment.unknown_id == unknown_id,
                UnknownAssignment.cancelled_at.is_(None),
            )
        ).scalar_one_or_none()

        if assignment is None:
            typer.echo(
                f"Error: No active assignment found for unknown '{unknown_id}' in grader run '{grader_run_id}'",
                err=True,
            )
            raise typer.Exit(1)

        assignment.cancelled_at = datetime.now(UTC)
        assignment.cancellation_reason = reason

    typer.echo(f"Cancelled assignment for {unknown_id}")


@app.command("init")
def init_cmd() -> None:
    """Run bootstrap (called by /init script)."""
    render_agent_prompt("props/docs/agents/clustering.md.j2")
