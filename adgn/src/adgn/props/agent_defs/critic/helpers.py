"""Helper functions for reporting issues. agent_run_id is auto-fetched from RLS context."""

from __future__ import annotations

from adgn.props.agent_helpers import get_current_agent_run_id, mcp_client_from_env
from adgn.props.db import get_session
from adgn.props.db.models import ReportedIssue, ReportedIssueOccurrence
from adgn.props.db.snapshots import DBLocationAnchor


def insert_issue(issue_id: str, rationale: str) -> None:
    """Insert a reported issue."""
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        issue = ReportedIssue(agent_run_id=agent_run_id, issue_id=issue_id, rationale=rationale)
        session.add(issue)


def insert_occurrence(issue_id: str, file: str, start_line: int | None = None, end_line: int | None = None) -> None:
    """Insert a single-location occurrence. Call insert_issue() first."""
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        occurrence = ReportedIssueOccurrence(
            agent_run_id=agent_run_id,
            reported_issue_id=issue_id,
            locations=[DBLocationAnchor(file=file, start_line=start_line, end_line=end_line)],
        )
        session.add(occurrence)


def insert_occurrence_multi(issue_id: str, locations: list[tuple[str, int | None, int | None]]) -> None:
    """Insert a multi-location occurrence (e.g., duplication across files).

    Args:
        locations: List of (file, start_line, end_line) tuples
    """
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)
        occurrence = ReportedIssueOccurrence(
            agent_run_id=agent_run_id,
            reported_issue_id=issue_id,
            locations=[DBLocationAnchor(file=f, start_line=start, end_line=end) for f, start, end in locations],
        )
        session.add(occurrence)


def delete_issue(issue_id: str) -> None:
    """Delete a reported issue and its occurrences (CASCADE)."""
    with get_session() as session:
        session.delete(session.query(ReportedIssue).filter_by(issue_id=issue_id).one())


async def submit_critique(issues_count: int, summary: str) -> None:
    """Call MCP submit tool to finalize. Must be awaited or use asyncio.run()."""
    async with mcp_client_from_env() as (client, _init_result):
        await client.call_tool("submit", {"issues_count": issues_count, "summary": summary})
