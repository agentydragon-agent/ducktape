"""Clustering agent CLI helper commands.

Provides CLI access to clustering helper functions for debugging and manual testing.

Usage:
    adgn-properties agent-helper clustering create-cluster "unused-imports" "Unused imports that add no value"
    adgn-properties agent-helper clustering assign-to-cluster "12345678-1234-..." "input-issue-5" "unused-imports" "Rationale"
    adgn-properties agent-helper clustering assign-to-tp "12345678-1234-..." "input-issue-10" "dead-code-utils" "Rationale"
    adgn-properties agent-helper clustering assign-to-fp "12345678-1234-..." "input-issue-15" "acceptable-duplication" "Rationale"
    adgn-properties agent-helper clustering cancel-assignment "12345678-1234-..." "input-issue-5" "Reassigning to different cluster"
"""

from __future__ import annotations

import typer

from adgn.props.clustering.helpers import (
    assign_to_cluster,
    assign_to_existing_fp,
    assign_to_existing_tp,
    cancel_assignment,
    create_cluster,
)

app = typer.Typer(help="Clustering agent helper commands")


@app.command("create-cluster")
def clustering_create_cluster(
    cluster_name: str = typer.Argument(..., help="Kebab-case cluster name (e.g., 'unused-imports')"),
    description: str = typer.Argument(..., help="Description of what this cluster represents"),
) -> None:
    """Create a new cluster for grouping unknown issues.

    Example:
        adgn-properties agent-helper clustering create-cluster "unused-imports" "Unused imports that add no value"
    """
    cluster_id = create_cluster(cluster_name=cluster_name, description=description)
    typer.echo(f"Created cluster '{cluster_name}' with ID: {cluster_id}")


@app.command("assign-to-cluster")
def clustering_assign_to_cluster(
    grader_run_id: str = typer.Argument(..., help="UUID of the grader run"),
    unknown_id: str = typer.Argument(..., help="ID of the unknown issue"),
    cluster_name: str = typer.Argument(..., help="Name of the cluster to assign to"),
    rationale: str = typer.Argument(..., help="Explanation for this assignment"),
) -> None:
    """Assign an unknown issue to a cluster.

    Example:
        adgn-properties agent-helper clustering assign-to-cluster \\
            "12345678-1234-..." "input-issue-5" "unused-imports" \\
            "Unused import of typing.cast in utils.py:15"
    """
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
    """Assign an unknown issue to an existing True Positive.

    Use when an unknown should have been matched to an existing TP.

    Example:
        adgn-properties agent-helper clustering assign-to-tp \\
            "12345678-1234-..." "input-issue-10" "dead-code-utils" \\
            "Same dead code issue as TP dead-code-utils"
    """
    assign_to_existing_tp(grader_run_id=grader_run_id, unknown_id=unknown_id, tp_id=tp_id, rationale=rationale)
    typer.echo(f"Assigned {unknown_id} to existing TP '{tp_id}'")


@app.command("assign-to-fp")
def clustering_assign_to_fp(
    grader_run_id: str = typer.Argument(..., help="UUID of the grader run"),
    unknown_id: str = typer.Argument(..., help="ID of the unknown issue"),
    fp_id: str = typer.Argument(..., help="ID of the existing false positive"),
    rationale: str = typer.Argument(..., help="Explanation for this assignment"),
) -> None:
    """Assign an unknown issue to an existing False Positive.

    Use when an unknown is a known acceptable pattern.

    Example:
        adgn-properties agent-helper clustering assign-to-fp \\
            "12345678-1234-..." "input-issue-15" "acceptable-duplication" \\
            "Duplication for visual consistency"
    """
    assign_to_existing_fp(grader_run_id=grader_run_id, unknown_id=unknown_id, fp_id=fp_id, rationale=rationale)
    typer.echo(f"Assigned {unknown_id} to existing FP '{fp_id}'")


@app.command("cancel-assignment")
def clustering_cancel_assignment(
    grader_run_id: str = typer.Argument(..., help="UUID of the grader run"),
    unknown_id: str = typer.Argument(..., help="ID of the unknown issue"),
    reason: str = typer.Argument(..., help="Reason for cancelling the assignment"),
) -> None:
    """Cancel an existing assignment (soft delete).

    Use to undo an incorrect assignment before creating a new one.

    Example:
        adgn-properties agent-helper clustering cancel-assignment \\
            "12345678-1234-..." "input-issue-5" "Reassigning to different cluster"
    """
    cancel_assignment(grader_run_id=grader_run_id, unknown_id=unknown_id, cancellation_reason=reason)
    typer.echo(f"Cancelled assignment for {unknown_id}")
