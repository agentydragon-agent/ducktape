"""Grader agent CLI for matching critique findings to ground truth.

Commands for adding grading decisions (TP/FP/no-match), then submitting.
Used by grader agents running inside containers.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from props_core.agent_helpers import get_grading_context
from props_core.grader.decision_helpers import (
    delete_decision,
    insert_fp_match,
    insert_no_match,
    insert_tp_match,
    submit_grading,
)
import typer

from agent_container_util.output import render_agent_prompt

HELP_TEXT = """Grader agent commands for matching critique findings to ground truth.

Common workflow:

  Match input to a True Positive (found a real issue):
    props grader-agent match input-001 tp tp-042 occ-001 1.0 "Exact match"

  Match input to a False Positive (triggered known acceptable pattern):
    props grader-agent match input-003 fp fp-015 occ-001 "Known pattern"

  Mark as novel finding (no ground truth match):
    props grader-agent match input-099 none "Novel architectural suggestion"

  Fix a mistake:
    props grader-agent delete-decision input-002

  Finalize and submit:
    props grader-agent submit "Graded 5 inputs: 3 TP matches, 2 novel"
"""

app = typer.Typer(name="grader-agent", help=HELP_TEXT, add_completion=False)


@app.command("match")
def match_cmd(
    input_issue_id: Annotated[str, typer.Argument(help="ID of the input issue from the critique")],
    match_type: Annotated[str, typer.Argument(help="Match type: 'tp', 'fp', or 'none'")],
    target_id: Annotated[str | None, typer.Argument(help="TP or FP ID (required for tp/fp)")] = None,
    occurrence_id: Annotated[str | None, typer.Argument(help="Occurrence ID (required for tp/fp)")] = None,
    credit_or_rationale: Annotated[str | None, typer.Argument(help="Credit (for tp) or rationale")] = None,
    rationale: Annotated[str | None, typer.Argument(help="Rationale (for tp; for fp/none, use previous arg)")] = None,
) -> None:
    """Add a grading decision matching input issue to ground truth.

    Usage patterns:
        match <input> tp <tp-id> <occ-id> <credit> <rationale>
        match <input> fp <fp-id> <occ-id> <rationale>
        match <input> none <rationale>

    Examples:
        props grader-agent match input-001 tp tp-042 occ-001 1.0 "Exact match"
        props grader-agent match input-003 fp fp-015 occ-001 "Known pattern"
        props grader-agent match input-099 none "Novel architectural suggestion"
    """
    match_type_lower = match_type.lower()

    if match_type_lower == "tp":
        if target_id is None or occurrence_id is None or credit_or_rationale is None or rationale is None:
            typer.echo("Error: tp requires: <tp-id> <occurrence-id> <credit> <rationale>", err=True)
            raise typer.Exit(1)
        credit = float(credit_or_rationale)
        insert_tp_match(
            input_issue_id=input_issue_id,
            tp_id=target_id,
            tp_occurrence_id=occurrence_id,
            credit=credit,
            rationale=rationale,
        )
        typer.echo(f"Added TP match: {input_issue_id} -> {target_id}/{occurrence_id} (credit={credit})")

    elif match_type_lower == "fp":
        if target_id is None or occurrence_id is None or credit_or_rationale is None:
            typer.echo("Error: fp requires: <fp-id> <occurrence-id> <rationale>", err=True)
            raise typer.Exit(1)
        # For fp, credit_or_rationale is actually the rationale
        insert_fp_match(
            input_issue_id=input_issue_id,
            fp_id=target_id,
            fp_occurrence_id=occurrence_id,
            rationale=credit_or_rationale,
        )
        typer.echo(f"Added FP match: {input_issue_id} -> {target_id}/{occurrence_id}")

    elif match_type_lower == "none":
        if target_id is None:
            typer.echo("Error: none requires: <rationale>", err=True)
            raise typer.Exit(1)
        # For none, target_id is actually the rationale
        insert_no_match(input_issue_id=input_issue_id, rationale=target_id)
        typer.echo(f"Added no-match decision: {input_issue_id}")

    else:
        typer.echo(f"Error: Unknown match type: {match_type}. Use 'tp', 'fp', or 'none'.", err=True)
        raise typer.Exit(1)


@app.command("delete-decision")
def delete_decision_cmd(
    input_issue_id: Annotated[str, typer.Argument(help="ID of the input issue whose decision to delete")],
) -> None:
    """Delete a grading decision for an input issue.

    Example:
        props grader-agent delete-decision input-002
    """
    delete_decision(input_issue_id=input_issue_id)
    typer.echo(f"Deleted decision for: {input_issue_id}")


@app.command("submit")
def submit_cmd(summary: Annotated[str, typer.Argument(help="Brief summary of grading results")]) -> None:
    """Submit the grading (finalize and call MCP submit).

    Example:
        props grader-agent submit "Graded 5 inputs: 3 TP matches, 2 novel"
    """
    asyncio.run(submit_grading(summary=summary))
    typer.echo("Grading submitted successfully")


@app.command("init")
def init_cmd() -> None:
    """Run bootstrap (called by /init script)."""
    render_agent_prompt("props/docs/agents/grader.md.j2", helpers={"grading_context": get_grading_context()})
