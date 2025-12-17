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

# Avoid circular import - only use for type checking
from typing import TYPE_CHECKING

from adgn.props.critic.models import (
    CriticContextLengthExceeded,
    CriticMaxTurnsExceeded,
    CriticOutput,
    CriticReportedFailure,
    CriticSubmitPayload,
    CriticSuccess,
    Occurrence,
    ReportedIssue,
)
from adgn.props.db.models import ReportedIssue as ORMReportedIssue
from adgn.props.db.snapshots import (
    DBCriticContextLengthExceeded,
    DBCriticMaxTurnsExceeded,
    DBCriticOutput,
    DBCriticReportedFailure,
    DBCriticSubmitPayload,
    DBCriticSuccess,
    DBFileOccurrence,
    DBLineRange,
    DBOccurrence,
    DBReportedIssue,
)
from adgn.props.models.true_positive import FileOccurrence, LineRange

if TYPE_CHECKING:
    from adgn.props.db.models import ReportedIssueOccurrence


def _convert_line_range_to_db(lr: LineRange) -> DBLineRange:
    """Convert MCP LineRange to DB representation."""
    return DBLineRange(start_line=lr.start_line, end_line=lr.end_line)


def _convert_file_occurrence_to_db(fo: FileOccurrence) -> DBFileOccurrence:
    """Convert MCP FileOccurrence to DB representation."""
    return DBFileOccurrence(
        path=str(fo.path), ranges=[_convert_line_range_to_db(lr) for lr in fo.ranges] if fo.ranges else None
    )


def _convert_occurrence_to_db(occ: Occurrence) -> DBOccurrence:
    """Convert MCP Occurrence to DB representation."""
    return DBOccurrence(files=[_convert_file_occurrence_to_db(fo) for fo in occ.files], note=occ.note)


def reported_issue_to_db(issue: ReportedIssue) -> DBReportedIssue:
    """Convert MCP ReportedIssue to DB representation."""
    return DBReportedIssue(
        id=str(issue.id),
        rationale=str(issue.rationale),
        occurrences=[_convert_occurrence_to_db(occ) for occ in issue.occurrences],
    )


def critic_submit_payload_to_db(payload: CriticSubmitPayload) -> DBCriticSubmitPayload:
    """Convert MCP CriticSubmitPayload to DB representation.

    Note: Issues are NOT stored in DB payload (they go to normalized tables).
    This only converts the notes_md field.
    """
    return DBCriticSubmitPayload(notes_md=payload.notes_md)


def critic_output_to_db(output: CriticOutput) -> DBCriticOutput:
    """Convert MCP CriticOutput (discriminated union) to DB representation."""
    if isinstance(output, CriticSuccess):
        return DBCriticSuccess(result=critic_submit_payload_to_db(output.result))
    if isinstance(output, CriticMaxTurnsExceeded):
        return DBCriticMaxTurnsExceeded(max_turns=output.max_turns)
    if isinstance(output, CriticContextLengthExceeded):
        return DBCriticContextLengthExceeded(error_message=output.error_message)
    if isinstance(output, CriticReportedFailure):
        return DBCriticReportedFailure(reason=output.reason)
    raise TypeError(f"Unexpected CriticOutput variant: {type(output)}")


# =============================================================================
# ORM to Domain/DB Conversions
# =============================================================================


def convert_reported_occurrence_orm_to_mcp(occ: ReportedIssueOccurrence) -> Occurrence:
    """Convert ORM ReportedIssueOccurrence to MCP Occurrence.

    Groups locations by file to create FileOccurrence objects with consolidated ranges.
    Used in submit_server.py get_critique tool.
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
    from adgn.props.ids import InputIssueID
    from adgn.props.rationale import Rationale

    return ReportedIssue(
        id=InputIssueID(issue.issue_id),
        rationale=Rationale(issue.rationale),
        occurrences=[convert_reported_occurrence_orm_to_mcp(occ) for occ in issue.occurrences],
    )


def convert_reported_occurrence_orm_to_db(occ: ReportedIssueOccurrence) -> DBOccurrence:
    """Convert ORM ReportedIssueOccurrence to DB DBOccurrence.

    Groups locations by file to create DBFileOccurrence objects with consolidated ranges.
    Used when constructing critic success output from reported issues.
    """
    locations_by_file = defaultdict(list)
    for loc in occ.locations:
        if loc.start_line is not None:
            locations_by_file[loc.file].append(DBLineRange(start_line=loc.start_line, end_line=loc.end_line))

    return DBOccurrence(
        files=[
            DBFileOccurrence(path=file_path, ranges=ranges if ranges else None)
            for file_path, ranges in locations_by_file.items()
        ],
        note=None,
    )


def convert_reported_issue_orm_to_db(
    issue: ORMReportedIssue, occurrences: list[ReportedIssueOccurrence]
) -> DBReportedIssue:
    """Convert ORM ReportedIssue to DB representation.

    Args:
        issue: The ORM ReportedIssue model
        occurrences: List of ORM ReportedIssueOccurrence models for this issue

    Returns:
        DB representation of the reported issue with converted occurrences
    """
    return DBReportedIssue(
        id=issue.issue_id,
        rationale=issue.rationale,
        occurrences=[convert_reported_occurrence_orm_to_db(occ) for occ in occurrences],
    )


def load_critic_submit_payload_mcp(session, critic_run_id, notes_md: str | None = None) -> CriticSubmitPayload:
    """Load CriticSubmitPayload (MCP type) from database for a given critic run.

    Args:
        session: SQLAlchemy session
        critic_run_id: UUID of the critic run
        notes_md: Optional notes in markdown (typically from critic_run.completion_summary)

    Returns:
        MCP CriticSubmitPayload reconstructed from normalized tables
    """
    reported_issues = session.query(ORMReportedIssue).filter_by(critic_run_id=critic_run_id).all()
    return CriticSubmitPayload(
        issues=[convert_reported_issue_orm_to_mcp(issue) for issue in reported_issues], notes_md=notes_md
    )
