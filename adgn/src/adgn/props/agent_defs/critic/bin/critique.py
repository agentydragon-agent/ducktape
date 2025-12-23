#!/usr/bin/env python3
"""Critic CLI for reporting issues."""

import asyncio
import sys
from typing import Annotated

# Add workspace to path for local imports (helpers.py, etc.)
sys.path.insert(0, "/workspace")

from helpers import (  # type: ignore[import-not-found]
    delete_issue,
    insert_issue,
    insert_occurrence,
    insert_occurrence_multi,
    submit_critique,
)
import typer

from adgn.props.agent_helpers import get_current_agent_run_id
from adgn.props.db import get_session
from adgn.props.db.models import ReportedIssue, ReportedIssueOccurrence

HELP_TEXT = """Critic agent commands for reporting code review findings.

Common workflow:

  Report an issue with a single location:
    /workspace/bin/critique.py insert-issue dead-import "Unused import detected"
    /workspace/bin/critique.py insert-occurrence dead-import server.py -s 10 -e 10

  Report duplication across multiple files:
    /workspace/bin/critique.py insert-issue dup-enum "Enum duplicated in two files"
    /workspace/bin/critique.py insert-occurrence-multi dup-enum types.py:20:25 persist.py:54:58

  Fix a mistake:
    /workspace/bin/critique.py delete-issue wrong-issue

  Finalize and submit:
    /workspace/bin/critique.py list-issues
    /workspace/bin/critique.py submit 3 "Found 1 dead code and 2 duplication issues"
"""

app = typer.Typer(name="critique", help=HELP_TEXT, add_completion=False)


@app.command("insert-issue")
def insert_issue_cmd(
    issue_id: Annotated[str, typer.Argument(help="Unique identifier for this issue")],
    rationale: Annotated[str, typer.Argument(help="Explanation of why this is an issue")],
) -> None:
    """Insert a reported issue.

    Example:
        critique insert-issue dead-import "Unused import detected in server.py"
    """
    insert_issue(issue_id=issue_id, rationale=rationale)
    typer.echo(f"✓ Inserted issue: {issue_id}")


@app.command("insert-occurrence")
def insert_occurrence_cmd(
    issue_id: Annotated[str, typer.Argument(help="ID of the issue this occurrence belongs to")],
    file: Annotated[str, typer.Argument(help="File path relative to workspace root")],
    start_line: Annotated[int | None, typer.Option("--start-line", "-s", help="Starting line number")] = None,
    end_line: Annotated[int | None, typer.Option("--end-line", "-e", help="Ending line number")] = None,
) -> None:
    """Insert a single-location occurrence for a reported issue.

    Example:
        critique insert-occurrence dead-import server.py --start-line 10 --end-line 10
        critique insert-occurrence unused-func utils.py -s 45 -e 60
    """
    insert_occurrence(issue_id=issue_id, file=file, start_line=start_line, end_line=end_line)
    location = file
    if start_line is not None:
        location += f":{start_line}"
        if end_line is not None and end_line != start_line:
            location += f"-{end_line}"
    typer.echo(f"✓ Inserted occurrence for {issue_id}: {location}")


@app.command("insert-occurrence-multi")
def insert_occurrence_multi_cmd(
    issue_id: Annotated[str, typer.Argument(help="ID of the issue this occurrence belongs to")],
    locations: Annotated[list[str], typer.Argument(help="Location specs as file:start:end (e.g., 'server.py:10:20')")],
) -> None:
    """Insert a multi-location occurrence (e.g., duplication across files).

    Location format: file:start_line:end_line
    Use ':' or '::' for missing line numbers.

    Examples:
        critique insert-occurrence-multi dup-enum types.py:20:25 persist.py:54:58
        critique insert-occurrence-multi related-code a.py:10:20 b.py:30:40 c.py:50:60
    """
    parsed: list[tuple[str, int | None, int | None]] = []
    for loc in locations:
        parts = loc.split(":")
        if len(parts) == 1:
            parsed.append((parts[0], None, None))
        elif len(parts) == 2:
            parsed.append((parts[0], int(parts[1]) if parts[1] else None, None))
        elif len(parts) >= 3:
            parsed.append((parts[0], int(parts[1]) if parts[1] else None, int(parts[2]) if parts[2] else None))

    insert_occurrence_multi(issue_id=issue_id, locations=parsed)
    typer.echo(f"✓ Inserted multi-location occurrence for {issue_id}: {len(parsed)} locations")


@app.command("delete-issue")
def delete_issue_cmd(issue_id: Annotated[str, typer.Argument(help="ID of the issue to delete")]) -> None:
    """Delete a reported issue and all its occurrences.

    Use this to remove an incorrect issue before inserting a corrected one.

    Example:
        critique delete-issue wrong-issue
    """
    delete_issue(issue_id=issue_id)
    typer.echo(f"✓ Deleted issue: {issue_id}")


@app.command("submit")
def submit_cmd(
    issues_count: Annotated[int, typer.Argument(help="Total number of issues reported")],
    summary: Annotated[str, typer.Argument(help="Brief summary of the code review findings")],
) -> None:
    """Finalize the critique by calling the MCP submit tool.

    This marks the critique as complete and validates that all issues
    have been properly reported with occurrences.

    Example:
        critique submit 3 "Found 1 dead code issue and 2 duplication issues"
    """
    asyncio.run(submit_critique(issues_count=issues_count, summary=summary))
    typer.echo(f"✓ Submitted critique: {issues_count} issues")


@app.command("list-issues")
def list_issues_cmd() -> None:
    """List all issues reported in this critique run.

    Shows issue IDs, rationales, and occurrence counts.
    """
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        issues = session.query(ReportedIssue).filter_by(agent_run_id=agent_run_id).all()

        if not issues:
            typer.echo("No issues reported yet.")
            return

        typer.echo(f"Issues reported ({len(issues)}):\n")
        for issue in issues:
            occurrences = (
                session.query(ReportedIssueOccurrence)
                .filter_by(agent_run_id=agent_run_id, reported_issue_id=issue.issue_id)
                .all()
            )
            typer.echo(f"  {issue.issue_id}")
            typer.echo(f"    Rationale: {issue.rationale}")
            typer.echo(f"    Occurrences: {len(occurrences)}")
            for occ in occurrences:
                locs = ", ".join(f"{loc.file}:{loc.start_line or '?'}-{loc.end_line or '?'}" for loc in occ.locations)
                typer.echo(f"      - {locs}")
            typer.echo()


@app.command("run-info")
def run_info_cmd() -> None:
    """Show current agent run information."""
    typer.echo("Agent Run Info:")

    try:
        with get_session() as session:
            agent_run_id = get_current_agent_run_id(session)
            typer.echo(f"  agent_run_id: {agent_run_id}")
    except Exception as e:
        typer.echo(f"  agent_run_id: Error: {e}", err=True)


if __name__ == "__main__":
    app()
