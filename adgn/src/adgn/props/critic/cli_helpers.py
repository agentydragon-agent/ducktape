"""Critic agent CLI helper commands.

Provides CLI access to critic helper functions for debugging and manual testing.

Usage:
    adgn-properties agent-helper critic add-issue "dead-import" "Unused import"
    adgn-properties agent-helper critic add-occurrence "dead-import" "server.py" -s 10 -e 10
    adgn-properties agent-helper critic submit 3 "Found 3 issues"
"""

from __future__ import annotations

import typer

from adgn.cli_utils import async_run
from adgn.props.critic.helpers import insert_issue, insert_occurrence, submit_critique

app = typer.Typer(help="Critic agent helper commands")


@app.command("add-issue")
def add_issue(
    issue_id: str = typer.Argument(..., help="Unique issue identifier"),
    rationale: str = typer.Argument(..., help="Why this is an issue"),
) -> None:
    """Add an issue to the current critic run.

    Example:
        adgn-properties agent-helper critic add-issue "dead-import" "Unused import in server.py"
    """
    insert_issue(issue_id=issue_id, rationale=rationale)
    typer.echo(f"Added issue: {issue_id}")


@app.command("add-occurrence")
def add_occurrence(
    issue_id: str = typer.Argument(..., help="Issue ID this occurrence belongs to"),
    file: str = typer.Argument(..., help="File path relative to workspace"),
    start_line: int | None = typer.Option(None, "--start", "-s", help="Start line number"),
    end_line: int | None = typer.Option(None, "--end", "-e", help="End line number"),
) -> None:
    """Add a single-file occurrence for an issue.

    Example:
        adgn-properties agent-helper critic add-occurrence "dead-import" "server.py" -s 10 -e 10
    """
    insert_occurrence(issue_id=issue_id, file=file, start_line=start_line, end_line=end_line)
    typer.echo(f"Added occurrence for {issue_id}: {file}")


@app.command("submit")
@async_run
async def submit(
    issues_count: int = typer.Argument(..., help="Number of issues reported"),
    summary: str = typer.Argument(..., help="Brief summary of findings"),
) -> None:
    """Submit the critique (finalize and call MCP submit).

    Example:
        adgn-properties agent-helper critic submit 3 "Found 3 dead code issues"
    """
    await submit_critique(issues_count=issues_count, summary=summary)
    typer.echo("Critique submitted successfully")
