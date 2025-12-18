"""Helper functions for inserting reported issues and calling the submit tool.

These helpers simplify the critic workflow by providing typed interfaces
for creating reported issues, their occurrences, and finalizing the critique.

Database session is obtained automatically using get_session() which respects
the critic agent's RLS-scoped credentials. The critic_run_id is automatically
fetched via the current_critic_run_id() database function.

Typical workflow:
    1. Call insert_issue() for each issue found
    2. Call insert_occurrence() or insert_occurrence_multi() for each issue
    3. Call submit_critique() to finalize and mark the critique complete
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from adgn.props.agent_helpers import mcp_client_from_env
from adgn.props.db import get_session
from adgn.props.db.models import ReportedIssue, ReportedIssueOccurrence
from adgn.props.db.snapshots import DBLocationAnchor


def _get_current_critic_run_id(session) -> UUID:
    """Get the current critic run ID from the database.

    Uses the PostgreSQL current_critic_run_id() function which extracts
    the UUID from the database username (critic_agent_{uuid} pattern).

    Args:
        session: Active SQLAlchemy session

    Returns:
        UUID of the current critic run

    Raises:
        RuntimeError: If not connected as critic agent
    """
    result = session.execute(text("SELECT current_critic_run_id()"))
    critic_run_id = result.scalar()
    if not isinstance(critic_run_id, UUID):
        critic_run_id = UUID(str(critic_run_id))
    return critic_run_id


def insert_issue(issue_id: str, rationale: str) -> None:
    """Insert a reported issue.

    Args:
        issue_id: Unique identifier for this issue
        rationale: Explanation of why this is an issue

    Example:
        from adgn.props.critic.helpers import insert_issue

        insert_issue(
            issue_id="dead-import",
            rationale="Unused import detected in server.py"
        )

    Note:
        The critic_run_id is automatically fetched from the database using current_critic_run_id().
        You must be connected as a critic agent user (critic_agent_{run_id}).
    """
    with get_session() as session:
        critic_run_id = _get_current_critic_run_id(session)
        issue = ReportedIssue(critic_run_id=critic_run_id, issue_id=issue_id, rationale=rationale)
        session.add(issue)


def insert_occurrence(issue_id: str, file: str, start_line: int | None = None, end_line: int | None = None) -> None:
    """Insert a single-location occurrence for a reported issue.

    Args:
        issue_id: ID of the issue this occurrence belongs to
        file: File path relative to workspace root
        start_line: Optional starting line number
        end_line: Optional ending line number

    Example:
        from adgn.props.critic.helpers import insert_issue, insert_occurrence

        # First insert the issue
        insert_issue("dead-import", "Unused import in server.py")

        # Then insert occurrence(s)
        insert_occurrence(
            issue_id="dead-import",
            file="server.py",
            start_line=10,
            end_line=10
        )

    Note:
        The critic_run_id is automatically fetched from the database using current_critic_run_id().
        You must call insert_issue() before calling insert_occurrence().
    """
    with get_session() as session:
        critic_run_id = _get_current_critic_run_id(session)
        occurrence = ReportedIssueOccurrence(
            critic_run_id=critic_run_id,
            reported_issue_id=issue_id,
            locations=[DBLocationAnchor(file=file, start_line=start_line, end_line=end_line)],
        )
        session.add(occurrence)


def insert_occurrence_multi(issue_id: str, locations: list[tuple[str, int | None, int | None]]) -> None:
    """Insert a multi-location occurrence for a reported issue.

    Use this when an issue spans multiple files or has multiple code locations.

    Args:
        issue_id: ID of the issue this occurrence belongs to
        locations: List of (file, start_line, end_line) tuples

    Example:
        from adgn.props.critic.helpers import insert_issue, insert_occurrence_multi

        # Duplication across two files
        insert_issue("duplicated-validation", "Same validation logic duplicated")

        insert_occurrence_multi(
            issue_id="duplicated-validation",
            locations=[
                ("server.py", 45, 60),
                ("client.py", 120, 135),
            ]
        )

    Note:
        Each tuple in locations should be (file_path, start_line, end_line).
        Use None for start_line/end_line if not applicable.
    """
    with get_session() as session:
        critic_run_id = _get_current_critic_run_id(session)
        occurrence = ReportedIssueOccurrence(
            critic_run_id=critic_run_id,
            reported_issue_id=issue_id,
            locations=[DBLocationAnchor(file=f, start_line=start, end_line=end) for f, start, end in locations],
        )
        session.add(occurrence)


def delete_issue(issue_id: str) -> None:
    """Delete a reported issue and all its occurrences.

    Use this to remove an incorrect issue before inserting a corrected one.
    Note: Critics have DELETE privilege on reported_issues, which cascades to occurrences.

    Args:
        issue_id: ID of the issue to delete

    Example:
        from adgn.props.critic.helpers import delete_issue, insert_issue

        # Delete an incorrect issue
        delete_issue(issue_id="wrong-issue")

        # Then insert the corrected issue
        insert_issue(
            issue_id="corrected-issue",
            rationale="Corrected rationale after review"
        )
    """
    with get_session() as session:
        # Query for the issue to delete (RLS ensures we only see our run's issues)
        issue = session.query(ReportedIssue).filter_by(issue_id=issue_id).first()
        if issue:
            # CASCADE will automatically delete associated occurrences
            session.delete(issue)


async def submit_critique(issues_count: int, summary: str) -> None:
    """Call the MCP submit tool to finalize the critique.

    This marks the critique as complete and validates that all issues have been properly
    reported with occurrences.

    Args:
        issues_count: Total number of issues reported
        summary: Brief summary of the code review findings

    Raises:
        ToolError: If the MCP call fails (raised automatically by fastmcp)

    Example:
        import asyncio
        from adgn.props.critic.helpers import insert_issue, insert_occurrence, submit_critique

        # Report findings
        insert_issue("dead-code", "Unused function in utils.py")
        insert_occurrence("dead-code", "utils.py", 45, 60)

        insert_issue("duplication", "Duplicated validation logic")
        insert_occurrence("duplication", "server.py", 100, 120)
        insert_occurrence("duplication", "client.py", 200, 220)

        # Finalize
        asyncio.run(submit_critique(
            issues_count=2,
            summary="Found 1 dead code issue and 1 duplication issue"
        ))

    Note:
        This function is async and must be called with asyncio.run() or await.
        The MCP server will validate that issues_count matches the actual count.
    """
    async with mcp_client_from_env() as (client, _init_result):
        # raise_on_error=True (default) raises ToolError on failure
        await client.call_tool("submit", {"issues_count": issues_count, "summary": summary})
