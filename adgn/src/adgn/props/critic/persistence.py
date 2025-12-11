"""Conversion functions between MCP I/O models and database persistence models.

This module lives in the critic layer because it needs to know about both:
- MCP I/O models (critic.models.CriticSubmitPayload, ReportedIssue, Occurrence)
- Database persistence models (db.snapshots.DBCriticSubmitPayload, etc.)

The database layer should not depend on MCP I/O types to avoid coupling
database migrations to protocol changes.
"""

from __future__ import annotations

from pathlib import Path

from adgn.props.critic.models import CriticSubmitPayload, Occurrence, ReportedIssue
from adgn.props.db.snapshots import DBCriticSubmitPayload, DBFileOccurrence, DBLineRange, DBOccurrence, DBReportedIssue
from adgn.props.ids import BaseIssueID
from adgn.props.models.true_positive import FileOccurrence, LineRange
from adgn.props.rationale import Rationale


def _convert_line_range_to_db(lr: LineRange) -> DBLineRange:
    """Convert MCP LineRange to DB representation."""
    return DBLineRange(start_line=lr.start_line, end_line=lr.end_line)


def _convert_line_range_from_db(db_lr: DBLineRange) -> LineRange:
    """Convert DB LineRange to MCP representation."""
    return LineRange(start_line=db_lr.start_line, end_line=db_lr.end_line)


def _convert_file_occurrence_to_db(fo: FileOccurrence) -> DBFileOccurrence:
    """Convert MCP FileOccurrence to DB representation."""
    return DBFileOccurrence(
        path=str(fo.path), ranges=[_convert_line_range_to_db(lr) for lr in fo.ranges] if fo.ranges else None
    )


def _convert_file_occurrence_from_db(db_fo: DBFileOccurrence) -> FileOccurrence:
    """Convert DB FileOccurrence to MCP representation."""
    return FileOccurrence(
        path=Path(db_fo.path), ranges=[_convert_line_range_from_db(lr) for lr in db_fo.ranges] if db_fo.ranges else None
    )


def _convert_occurrence_to_db(occ: Occurrence) -> DBOccurrence:
    """Convert MCP Occurrence to DB representation."""
    return DBOccurrence(files=[_convert_file_occurrence_to_db(fo) for fo in occ.files], note=occ.note)


def _convert_occurrence_from_db(db_occ: DBOccurrence) -> Occurrence:
    """Convert DB Occurrence to MCP representation."""
    return Occurrence(files=[_convert_file_occurrence_from_db(fo) for fo in db_occ.files], note=db_occ.note)


def reported_issue_to_db(issue: ReportedIssue) -> DBReportedIssue:
    """Convert MCP ReportedIssue to DB representation."""
    return DBReportedIssue(
        id=str(issue.id),
        rationale=str(issue.rationale),
        occurrences=[_convert_occurrence_to_db(occ) for occ in issue.occurrences],
    )


def reported_issue_from_db(db_issue: DBReportedIssue) -> ReportedIssue:
    """Convert DB ReportedIssue to MCP representation."""
    return ReportedIssue(
        id=BaseIssueID(db_issue.id),
        rationale=Rationale(db_issue.rationale),
        occurrences=[_convert_occurrence_from_db(occ) for occ in db_issue.occurrences],
    )


def critic_submit_payload_to_db(payload: CriticSubmitPayload) -> DBCriticSubmitPayload:
    """Convert MCP CriticSubmitPayload to DB representation."""
    return DBCriticSubmitPayload(
        issues=[reported_issue_to_db(issue) for issue in payload.issues], notes_md=payload.notes_md
    )


def critic_submit_payload_from_db(db_payload: DBCriticSubmitPayload) -> CriticSubmitPayload:
    """Convert DB CriticSubmitPayload to MCP representation."""
    return CriticSubmitPayload(
        issues=[reported_issue_from_db(issue) for issue in db_payload.issues], notes_md=db_payload.notes_md
    )
