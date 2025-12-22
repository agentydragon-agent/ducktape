#!/usr/bin/env python3
"""Grader agent CLI helper commands.

Provides CLI access to grader helper functions.

Usage:
    python /workspace/bin/grader.py add-tp-match "input-001" "tp-042" "occ-001" 1.0 "Exact match"
    python /workspace/bin/grader.py add-fp-match "input-003" "fp-015" "occ-001" "Known acceptable pattern"
    python /workspace/bin/grader.py add-no-match "input-099" "Novel architectural suggestion"
    python /workspace/bin/grader.py delete-decision "input-002"
    python /workspace/bin/grader.py submit "Graded 5 inputs: 3 TP matches, 2 novel findings"
"""

from __future__ import annotations

from pathlib import Path
import sys

# Add workspace to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import typer

from adgn.cli_utils import async_run
from adgn.props.grader.decision_helpers import (
    delete_decision,
    insert_fp_match,
    insert_no_match,
    insert_tp_match,
    submit_grading,
)

app = typer.Typer(help="Grader agent helper commands")


@app.command("add-tp-match")
def add_tp_match(
    input_issue_id: str = typer.Argument(..., help="ID of the input issue from the critique"),
    tp_id: str = typer.Argument(..., help="ID of the canonical true positive"),
    tp_occurrence_id: str = typer.Argument(..., help="ID of the TP occurrence"),
    credit: float = typer.Argument(..., help="Credit amount (0.0-1.0)"),
    rationale: str = typer.Argument(..., help="Explanation for this decision"),
) -> None:
    """Add a grading decision matching input issue to a true positive.

    Example:
        python /workspace/bin/grader.py add-tp-match "input-001" "tp-042" "occ-001" 1.0 "Exact match"
    """
    insert_tp_match(
        input_issue_id=input_issue_id,
        tp_id=tp_id,
        tp_occurrence_id=tp_occurrence_id,
        credit=credit,
        rationale=rationale,
    )
    typer.echo(f"Added TP match: {input_issue_id} -> {tp_id}/{tp_occurrence_id} (credit={credit})")


@app.command("add-fp-match")
def add_fp_match(
    input_issue_id: str = typer.Argument(..., help="ID of the input issue from the critique"),
    fp_id: str = typer.Argument(..., help="ID of the canonical false positive"),
    fp_occurrence_id: str = typer.Argument(..., help="ID of the FP occurrence"),
    rationale: str = typer.Argument(..., help="Explanation for this decision"),
) -> None:
    """Add a grading decision matching input issue to a false positive.

    FP matches indicate the input triggered a known acceptable pattern.
    Credit is always 0.0 for FP matches.

    Example:
        python /workspace/bin/grader.py add-fp-match "input-003" "fp-015" "occ-001" "Known acceptable pattern"
    """
    insert_fp_match(input_issue_id=input_issue_id, fp_id=fp_id, fp_occurrence_id=fp_occurrence_id, rationale=rationale)
    typer.echo(f"Added FP match: {input_issue_id} -> {fp_id}/{fp_occurrence_id}")


@app.command("add-no-match")
def add_no_match(
    input_issue_id: str = typer.Argument(..., help="ID of the input issue from the critique"),
    rationale: str = typer.Argument(..., help="Explanation why no match was found"),
) -> None:
    """Add a grading decision for an input issue with no canonical match.

    No-match decisions indicate the input is a novel finding not in ground truth.

    Example:
        python /workspace/bin/grader.py add-no-match "input-099" "Novel architectural suggestion"
    """
    insert_no_match(input_issue_id=input_issue_id, rationale=rationale)
    typer.echo(f"Added no-match decision: {input_issue_id}")


@app.command("delete-decision")
def grader_delete_decision(
    input_issue_id: str = typer.Argument(..., help="ID of the input issue whose decision to delete"),
) -> None:
    """Delete a grading decision for an input issue.

    Use this to remove an incorrect decision before inserting a corrected one.

    Example:
        python /workspace/bin/grader.py delete-decision "input-002"
    """
    delete_decision(input_issue_id=input_issue_id)
    typer.echo(f"Deleted decision for: {input_issue_id}")


@app.command("submit")
@async_run
async def submit(summary: str = typer.Argument(..., help="Brief summary of grading results")) -> None:
    """Submit the grading (finalize and call MCP submit).

    This marks the grading as complete and validates all decisions.

    Example:
        python /workspace/bin/grader.py submit "Graded 5 inputs: 3 TP matches, 2 novel findings"
    """
    await submit_grading(summary=summary)
    typer.echo("Grading submitted successfully")


if __name__ == "__main__":
    app()
