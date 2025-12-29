"""Conversion functions between MCP I/O models and database persistence models.

This module lives in the grader layer because it needs to know about both:
- MCP I/O models (grader.models.TruePositiveIssue, KnownFalsePositive)
- Database persistence models (db.snapshots.DBTruePositiveIssue, DBKnownFalsePositive)

The database layer should not depend on MCP I/O types to avoid coupling
database migrations to protocol changes.
"""

from __future__ import annotations

from pathlib import Path

from props_core.db.snapshots import (
    DBFalsePositiveOccurrence,
    DBKnownFalsePositive,
    DBLineRange,
    DBTruePositiveIssue,
    DBTruePositiveOccurrence,
)
from props_core.grader.models import FalsePositiveID, KnownFalsePositive, TruePositiveID, TruePositiveIssue
from props_core.models.true_positive import FalsePositiveOccurrence, LineRange, TruePositiveOccurrence
from props_core.rationale import Rationale


def _convert_line_range_to_db(lr: LineRange) -> DBLineRange:
    """Convert MCP LineRange to DB representation."""
    return DBLineRange(start_line=lr.start_line, end_line=lr.end_line)


def _convert_line_range_from_db(db_lr: DBLineRange) -> LineRange:
    """Convert DB LineRange to MCP representation."""
    return LineRange(start_line=db_lr.start_line, end_line=db_lr.end_line)


def convert_files_dict_to_db(files: dict[Path, list[LineRange] | None]) -> dict[str, list[DBLineRange] | None]:
    """Convert MCP files dict (Path -> list[LineRange]) to DB representation (str -> list[DBLineRange])."""
    return {
        str(path): [_convert_line_range_to_db(lr) for lr in ranges] if ranges else None
        for path, ranges in files.items()
    }


def convert_files_dict_from_db(files: dict[str, list[DBLineRange] | None]) -> dict[Path, list[LineRange] | None]:
    """Convert DB files dict (str -> list[DBLineRange]) to MCP representation (Path -> list[LineRange])."""
    return {
        Path(path): [_convert_line_range_from_db(lr) for lr in ranges] if ranges else None
        for path, ranges in files.items()
    }


def tp_to_db(tp: TruePositiveIssue) -> DBTruePositiveIssue:
    """Convert MCP TruePositiveIssue to DB representation."""
    return DBTruePositiveIssue(
        id=str(tp.id),
        rationale=str(tp.rationale),
        occurrences=[
            DBTruePositiveOccurrence(
                occurrence_id=occ.occurrence_id,
                files=convert_files_dict_to_db(occ.files),
                note=occ.note,
                critic_scopes_expected_to_recall=[[str(p) for p in fs] for fs in occ.critic_scopes_expected_to_recall],
            )
            for occ in tp.occurrences
        ],
    )


def tp_from_db(db_tp: DBTruePositiveIssue) -> TruePositiveIssue:
    """Convert DB TruePositiveIssue to MCP representation."""
    return TruePositiveIssue(
        id=TruePositiveID(db_tp.id),
        rationale=Rationale(db_tp.rationale),
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id=occ.occurrence_id,
                files=convert_files_dict_from_db(occ.files),
                note=occ.note,
                critic_scopes_expected_to_recall={
                    frozenset(Path(p) for p in fs) for fs in occ.critic_scopes_expected_to_recall
                },
            )
            for occ in db_tp.occurrences
        ],
    )


def fp_to_db(fp: KnownFalsePositive) -> DBKnownFalsePositive:
    """Convert MCP KnownFalsePositive to DB representation."""
    return DBKnownFalsePositive(
        id=str(fp.id),
        rationale=str(fp.rationale),
        occurrences=[
            DBFalsePositiveOccurrence(
                occurrence_id=occ.occurrence_id,
                files=convert_files_dict_to_db(occ.files),
                note=occ.note,
                relevant_files=[str(p) for p in occ.relevant_files],
            )
            for occ in fp.occurrences
        ],
    )


def fp_from_db(db_fp: DBKnownFalsePositive) -> KnownFalsePositive:
    """Convert DB KnownFalsePositive to MCP representation."""
    return KnownFalsePositive(
        id=FalsePositiveID(db_fp.id),
        rationale=Rationale(db_fp.rationale),
        occurrences=[
            FalsePositiveOccurrence(
                occurrence_id=occ.occurrence_id,
                files=convert_files_dict_from_db(occ.files),
                note=occ.note,
                relevant_files={Path(p) for p in occ.relevant_files},
            )
            for occ in db_fp.occurrences
        ],
    )
