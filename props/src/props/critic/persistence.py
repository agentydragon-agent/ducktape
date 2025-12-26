"""Conversion functions between MCP I/O models and database persistence models.

This module lives in the critic layer because it needs to know about both:
- MCP I/O models (critic.models.CriticSubmitPayload, ReportedIssue, Occurrence)
- Database persistence models (db.snapshots.DBCriticSubmitPayload, etc.)
- ORM models (db.models.ReportedIssueOccurrence)

The database layer should not depend on MCP I/O types to avoid coupling
database migrations to protocol changes.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from props.critic.models import CriticSubmitPayload, Occurrence, ReportedIssue
from props.db.models import ReportedIssue as ORMReportedIssue
from props.ids import InputIssueID
from props.models.true_positive import FileOccurrence, LineRange
from props.rationale import Rationale

if TYPE_CHECKING:
    from props.db.models import ReportedIssueOccurrence


# =============================================================================
# ORM to Domain/DB Conversions
# =============================================================================


def convert_reported_occurrence_orm_to_mcp(occ: ReportedIssueOccurrence) -> Occurrence:
    """Convert ORM ReportedIssueOccurrence to MCP Occurrence.

    Groups locations by file to create FileOccurrence objects with consolidated ranges.
    """
    locations_by_file = defaultdict(list)
    for loc in occ.locations:
        if loc.start_line is not None:
            locations_by_file[Path(loc.file)].append(LineRange(start_line=loc.start_line, end_line=loc.end_line))

    return Occurrence(
        files=[
            FileOccurrence(path=file_path, ranges=ranges if ranges else None)
            for file_path, ranges in locations_by_file.items()
        ],
        note=None,
    )


def convert_reported_issue_orm_to_mcp(issue: ORMReportedIssue) -> ReportedIssue:
    """Convert ORM ReportedIssue to MCP representation.

    Args:
        issue: The ORM ReportedIssue model (with occurrences relationship loaded)

    Returns:
        MCP representation of the reported issue with converted occurrences
    """
    return ReportedIssue(
        id=InputIssueID(issue.issue_id),
        rationale=Rationale(issue.rationale),
        occurrences=[convert_reported_occurrence_orm_to_mcp(occ) for occ in issue.occurrences],
    )


def load_critic_submit_payload_mcp(session, agent_run_id, notes_md: str | None = None) -> CriticSubmitPayload:
    """Load CriticSubmitPayload (MCP type) from database for a given agent run.

    Args:
        session: SQLAlchemy session
        agent_run_id: UUID of the agent run (critic agent)
        notes_md: Optional notes in markdown (typically from agent_run.completion_summary)

    Returns:
        MCP CriticSubmitPayload reconstructed from normalized tables
    """
    reported_issues = session.query(ORMReportedIssue).filter_by(agent_run_id=agent_run_id).all()
    return CriticSubmitPayload(
        issues=[convert_reported_issue_orm_to_mcp(issue) for issue in reported_issues], notes_md=notes_md
    )
