#!/usr/bin/env python3
"""Clustering agent CLI helper commands."""

from __future__ import annotations

from pathlib import Path
import sys

# Add workspace to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# helpers is available at runtime when executed from /workspace
from helpers import (  # type: ignore[import-not-found]
    assign_to_cluster,
    assign_to_existing_fp,
    assign_to_existing_tp,
    cancel_assignment,
    create_cluster,
)
import typer

HELP_TEXT = """Clustering agent commands for categorizing unknown issues.

Common workflows:

  Create a new cluster and assign issues:
    /workspace/bin/clustering.py create-cluster "unused-imports" "Imports with no usage"
    /workspace/bin/clustering.py assign-to-cluster "grader-run-uuid" "issue-5" "unused-imports" "Rationale"

  Link to existing ground truth:
    /workspace/bin/clustering.py assign-to-tp "grader-run-uuid" "issue-10" "dead-code-utils" "Same as TP"
    /workspace/bin/clustering.py assign-to-fp "grader-run-uuid" "issue-15" "acceptable-dup" "Known pattern"

  Correct a mistake:
    /workspace/bin/clustering.py cancel-assignment "grader-run-uuid" "issue-5" "Reassigning"
"""

app = typer.Typer(name="clustering", help=HELP_TEXT, add_completion=False)


@app.command("create-cluster")
def clustering_create_cluster(
    cluster_name: str = typer.Argument(..., help="Kebab-case cluster name (e.g., 'unused-imports')"),
    description: str = typer.Argument(..., help="Description of what this cluster represents"),
) -> None:
    """Create a new cluster for grouping unknown issues."""
    cluster_id = create_cluster(cluster_name=cluster_name, description=description)
    typer.echo(f"Created cluster '{cluster_name}' with ID: {cluster_id}")


@app.command("assign-to-cluster")
def clustering_assign_to_cluster(
    grader_run_id: str = typer.Argument(..., help="UUID of the grader run"),
    unknown_id: str = typer.Argument(..., help="ID of the unknown issue"),
    cluster_name: str = typer.Argument(..., help="Name of the cluster to assign to"),
    rationale: str = typer.Argument(..., help="Explanation for this assignment"),
) -> None:
    """Assign an unknown issue to a cluster."""
    assign_to_cluster(
        grader_run_id=grader_run_id, unknown_id=unknown_id, cluster_name=cluster_name, rationale=rationale
    )
    typer.echo(f"Assigned {unknown_id} to cluster '{cluster_name}'")


@app.command("assign-to-tp")
def clustering_assign_to_tp(
    grader_run_id: str = typer.Argument(..., help="UUID of the grader run"),
    unknown_id: str = typer.Argument(..., help="ID of the unknown issue"),
    tp_id: str = typer.Argument(..., help="ID of the existing true positive"),
    rationale: str = typer.Argument(..., help="Explanation for this assignment"),
) -> None:
    """Assign an unknown issue to an existing True Positive."""
    assign_to_existing_tp(grader_run_id=grader_run_id, unknown_id=unknown_id, tp_id=tp_id, rationale=rationale)
    typer.echo(f"Assigned {unknown_id} to existing TP '{tp_id}'")


@app.command("assign-to-fp")
def clustering_assign_to_fp(
    grader_run_id: str = typer.Argument(..., help="UUID of the grader run"),
    unknown_id: str = typer.Argument(..., help="ID of the unknown issue"),
    fp_id: str = typer.Argument(..., help="ID of the existing false positive"),
    rationale: str = typer.Argument(..., help="Explanation for this assignment"),
) -> None:
    """Assign an unknown issue to an existing False Positive."""
    assign_to_existing_fp(grader_run_id=grader_run_id, unknown_id=unknown_id, fp_id=fp_id, rationale=rationale)
    typer.echo(f"Assigned {unknown_id} to existing FP '{fp_id}'")


@app.command("cancel-assignment")
def clustering_cancel_assignment(
    grader_run_id: str = typer.Argument(..., help="UUID of the grader run"),
    unknown_id: str = typer.Argument(..., help="ID of the unknown issue"),
    reason: str = typer.Argument(..., help="Reason for cancelling the assignment"),
) -> None:
    """Cancel an existing assignment (soft delete)."""
    cancel_assignment(grader_run_id=grader_run_id, unknown_id=unknown_id, cancellation_reason=reason)
    typer.echo(f"Cancelled assignment for {unknown_id}")


if __name__ == "__main__":
    app()
