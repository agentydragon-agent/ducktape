"""Critic agent CLI for reporting code review findings.

Commands for inserting issues and occurrences, then submitting the critique.
Used by critic agents running inside containers.
"""

from __future__ import annotations

from typing import Annotated

import typer

from props.core.agent_helpers import get_current_agent_run_id
from props.core.db.models import AgentRun, AgentRunStatus, ReportedIssue, ReportedIssueOccurrence
from props.core.db.session import get_session
from props.core.db.snapshots import DBLocationAnchor

HELP_TEXT = """Critic agent commands for reporting code review findings.

Common workflow:

  Report an issue with a single location:
    props critic-agent insert-issue dead-import "Unused import detected"
    props critic-agent insert-occurrence dead-import server.py -s 10 -e 10

  Report duplication across multiple files:
    props critic-agent insert-issue dup-enum "Enum duplicated in two files"
    props critic-agent insert-occurrence-multi dup-enum types.py:20:25 persist.py:54:58

  Fix a mistake:
    props critic-agent delete-issue wrong-issue

  Finalize and submit:
    props critic-agent list-issues
    props critic-agent submit 3 "Found 1 dead code and 2 duplication issues"
"""

app = typer.Typer(name="critic-agent", help=HELP_TEXT, add_completion=False)


@app.command("insert-issue")
def insert_issue_cmd(
    issue_id: Annotated[str, typer.Argument(help="Unique identifier for this issue")],
    rationale: Annotated[str, typer.Argument(help="Explanation of why this is an issue")],
) -> None:
    """Insert a reported issue.

    Example:
        props critic-agent insert-issue dead-import "Unused import detected in server.py"
    """
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        issue = ReportedIssue(agent_run_id=agent_run_id, issue_id=issue_id, rationale=rationale)
        session.add(issue)
    typer.echo(f"Inserted issue: {issue_id}")


@app.command("insert-occurrence")
def insert_occurrence_cmd(
    issue_id: Annotated[str, typer.Argument(help="ID of the issue this occurrence belongs to")],
    file: Annotated[str, typer.Argument(help="File path relative to workspace root")],
    start_line: Annotated[int | None, typer.Option("--start-line", "-s", help="Starting line number")] = None,
    end_line: Annotated[int | None, typer.Option("--end-line", "-e", help="Ending line number")] = None,
) -> None:
    """Insert a single-location occurrence for a reported issue.

    Example:
        props critic-agent insert-occurrence dead-import server.py --start-line 10 --end-line 10
        props critic-agent insert-occurrence unused-func utils.py -s 45 -e 60
    """
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        occurrence = ReportedIssueOccurrence(
            agent_run_id=agent_run_id,
            reported_issue_id=issue_id,
            locations=[DBLocationAnchor(file=file, start_line=start_line, end_line=end_line)],
        )
        session.add(occurrence)

    location = file
    if start_line is not None:
        location += f":{start_line}"
        if end_line is not None and end_line != start_line:
            location += f"-{end_line}"
    typer.echo(f"Inserted occurrence for {issue_id}: {location}")


@app.command("insert-occurrence-multi")
def insert_occurrence_multi_cmd(
    issue_id: Annotated[str, typer.Argument(help="ID of the issue this occurrence belongs to")],
    locations: Annotated[list[str], typer.Argument(help="Location specs as file:start:end (e.g., 'server.py:10:20')")],
) -> None:
    """Insert a multi-location occurrence (e.g., duplication across files).

    Location format: file:start_line:end_line
    Use ':' or '::' for missing line numbers.

    Examples:
        props critic-agent insert-occurrence-multi dup-enum types.py:20:25 persist.py:54:58
        props critic-agent insert-occurrence-multi related-code a.py:10:20 b.py:30:40 c.py:50:60
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

    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        occurrence = ReportedIssueOccurrence(
            agent_run_id=agent_run_id,
            reported_issue_id=issue_id,
            locations=[DBLocationAnchor(file=f, start_line=start, end_line=end) for f, start, end in parsed],
        )
        session.add(occurrence)

    typer.echo(f"Inserted multi-location occurrence for {issue_id}: {len(parsed)} locations")


@app.command("delete-issue")
def delete_issue_cmd(issue_id: Annotated[str, typer.Argument(help="ID of the issue to delete")]) -> None:
    """Delete a reported issue and all its occurrences.

    Use this to remove an incorrect issue before inserting a corrected one.

    Example:
        props critic-agent delete-issue wrong-issue
    """
    with get_session() as session:
        issue = session.query(ReportedIssue).filter_by(issue_id=issue_id).first()
        if issue is None:
            typer.echo(f"Error: Issue not found: {issue_id}", err=True)
            raise typer.Exit(1)
        session.delete(issue)
    typer.echo(f"Deleted issue: {issue_id}")


def _validate_occurrence(occ: ReportedIssueOccurrence) -> str | None:
    """Validate a single occurrence. Returns error message or None if valid."""
    if not occ.locations or len(occ.locations) == 0:
        return f"Occurrence {occ.id} must have at least one location"

    for i, loc in enumerate(occ.locations):
        if not isinstance(loc, DBLocationAnchor):
            return f"Location {i} must be a DBLocationAnchor, got {type(loc)}"

        if loc.start_line is not None:
            if loc.start_line <= 0:
                return f"Location {i}: start_line must be > 0, got {loc.start_line}"

            if loc.end_line is not None and loc.end_line < loc.start_line:
                return f"Location {i}: end_line ({loc.end_line}) must be >= start_line ({loc.start_line})"

    return None


@app.command("submit")
def submit_cmd(
    issues_count: Annotated[int, typer.Argument(help="Total number of issues reported")],
    summary: Annotated[str, typer.Argument(help="Brief summary of the code review findings")],
) -> None:
    """Finalize the critique and validate reported issues.

    This validates all issues and occurrences, then marks the run as complete.
    Prints validation errors to stderr and exits with code 1 if validation fails.

    Validations:
    - Issues count must match actual reported issues
    - Every issue must have at least one occurrence
    - Each occurrence must have at least one location
    - Line ranges must be valid (start_line > 0, end_line >= start_line)

    Example:
        props critic-agent submit 3 "Found 1 dead code issue and 2 duplication issues"
    """
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        agent_run = session.get(AgentRun, agent_run_id)

        if agent_run is None:
            typer.echo(f"Error: Agent run {agent_run_id} not found", err=True)
            raise typer.Exit(1)

        if agent_run.status == AgentRunStatus.COMPLETED:
            typer.echo(f"Error: Agent run {agent_run_id} already completed", err=True)
            raise typer.Exit(1)

        issues = session.query(ReportedIssue).filter_by(agent_run_id=agent_run_id).all()

        actual_issues_count = len(issues)
        if issues_count != actual_issues_count:
            typer.echo(
                f"Error: Issues count mismatch: expected {issues_count} but found {actual_issues_count} in database",
                err=True,
            )
            raise typer.Exit(1)

        total_occurrences = 0
        for issue in issues:
            occurrences = (
                session.query(ReportedIssueOccurrence)
                .filter_by(agent_run_id=agent_run_id, reported_issue_id=issue.issue_id)
                .all()
            )

            if len(occurrences) == 0:
                typer.echo(
                    f"Error: Issue '{issue.issue_id}' has no occurrences. "
                    f"Every issue must have at least one occurrence showing where it occurs in the code.",
                    err=True,
                )
                raise typer.Exit(1)

            total_occurrences += len(occurrences)

            for occ in occurrences:
                error = _validate_occurrence(occ)
                if error:
                    typer.echo(f"Error: {error}", err=True)
                    raise typer.Exit(1)

        agent_run.status = AgentRunStatus.COMPLETED
        agent_run.completion_summary = summary

    typer.echo(f"Submitted critique: {issues_count} issues, {total_occurrences} occurrences")


@app.command("report-failure")
def report_failure_cmd(
    message: Annotated[str, typer.Argument(help="Description of why the critique could not be completed")],
) -> None:
    """Report that critique could not be completed.

    Call this when you encounter blocking issues that prevent review completion
    (e.g., no files matched scope, access issues, missing dependencies).

    This marks the run as failed and stores the error message.

    Example:
        props critic-agent report-failure "No Python files found in scope"
    """
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        agent_run = session.get(AgentRun, agent_run_id)

        if agent_run is None:
            typer.echo(f"Error: Agent run {agent_run_id} not found", err=True)
            raise typer.Exit(1)

        if agent_run.status == AgentRunStatus.COMPLETED:
            typer.echo(f"Error: Agent run {agent_run_id} already completed", err=True)
            raise typer.Exit(1)

        if agent_run.status == AgentRunStatus.REPORTED_FAILURE:
            typer.echo(f"Error: Agent run {agent_run_id} already reported failure", err=True)
            raise typer.Exit(1)

        agent_run.status = AgentRunStatus.REPORTED_FAILURE
        agent_run.completion_summary = message

    typer.echo(f"Reported failure: {message}")


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


def main() -> None:
    """Entry point for critic-cli binary."""
    app()


if __name__ == "__main__":
    main()
