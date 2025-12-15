"""Conversion functions between MCP I/O models and database persistence models.

This module lives in the grader layer because it needs to know about both:
- MCP I/O models (grader.models.TruePositiveIssue, KnownFalsePositive, GraderOutput)
- Database persistence models (db.snapshots.DBTruePositiveIssue, DBKnownFalsePositive)

The database layer should not depend on MCP I/O types to avoid coupling
database migrations to protocol changes.
"""

from __future__ import annotations

from pathlib import Path

from adgn.props.db.snapshots import (
    DBCanonicalFPCoverage,
    DBCanonicalTPCoverage,
    DBFalsePositiveOccurrence,
    DBGraderMaxTurnsExceeded,
    DBGraderOutput,
    DBGraderSuccess,
    DBIssueCoverageEntry,
    DBKnownFalsePositive,
    DBLineRange,
    DBOccurrenceMatch,
    DBOccurrenceResult,
    DBTruePositiveIssue,
    DBTruePositiveOccurrence,
    DBUnknownIssue,
)
from adgn.props.grader.models import (
    CanonicalFPCoverage,
    CanonicalTPCoverage,
    FalsePositiveID,
    GraderMaxTurnsExceeded,
    GraderOutput,
    GraderSuccess,
    InputIssueID,
    IssueCoverageEntry,
    KnownFalsePositive,
    OccurrenceMatch,
    OccurrenceResult,
    TruePositiveID,
    TruePositiveIssue,
    UnknownIssue,
)
from adgn.props.models.true_positive import FalsePositiveOccurrence, LineRange, TruePositiveOccurrence
from adgn.props.rationale import Rationale


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
                expect_caught_from=[[str(p) for p in fs] for fs in occ.expect_caught_from],
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
                expect_caught_from={frozenset(Path(p) for p in fs) for fs in occ.expect_caught_from},
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


def _issue_coverage_entry_to_db(entry: IssueCoverageEntry) -> DBIssueCoverageEntry:
    """Convert MCP IssueCoverageEntry to DB representation."""
    return DBIssueCoverageEntry(input_id=str(entry.input_id), credit=entry.credit)


def _issue_coverage_entry_from_db(db_entry: DBIssueCoverageEntry) -> IssueCoverageEntry:
    """Convert DB IssueCoverageEntry to MCP representation."""
    return IssueCoverageEntry(input_id=InputIssueID(db_entry.input_id), credit=db_entry.credit)


def _canonical_tp_coverage_to_db(coverage: CanonicalTPCoverage) -> DBCanonicalTPCoverage:
    """Convert MCP CanonicalTPCoverage to DB representation."""
    return DBCanonicalTPCoverage(
        covered_by=[_issue_coverage_entry_to_db(e) for e in coverage.covered_by],
        recall_credit=coverage.recall_credit,
        rationale=str(coverage.rationale),
    )


def _canonical_tp_coverage_from_db(db_coverage: DBCanonicalTPCoverage) -> CanonicalTPCoverage:
    """Convert DB CanonicalTPCoverage to MCP representation."""
    return CanonicalTPCoverage(
        covered_by=[_issue_coverage_entry_from_db(e) for e in db_coverage.covered_by],
        recall_credit=db_coverage.recall_credit,
        rationale=Rationale(db_coverage.rationale),
    )


def _canonical_fp_coverage_to_db(coverage: CanonicalFPCoverage) -> DBCanonicalFPCoverage:
    """Convert MCP CanonicalFPCoverage to DB representation."""
    return DBCanonicalFPCoverage(covered_by=[str(id) for id in coverage.covered_by], rationale=str(coverage.rationale))


def _canonical_fp_coverage_from_db(db_coverage: DBCanonicalFPCoverage) -> CanonicalFPCoverage:
    """Convert DB CanonicalFPCoverage to MCP representation."""
    return CanonicalFPCoverage(
        covered_by=[InputIssueID(id) for id in db_coverage.covered_by], rationale=Rationale(db_coverage.rationale)
    )


def _occurrence_match_to_db(match: OccurrenceMatch) -> DBOccurrenceMatch:
    """Convert MCP OccurrenceMatch to DB representation."""
    return DBOccurrenceMatch(input_id=str(match.input_id), credit=match.credit)


def _occurrence_result_to_db(result: OccurrenceResult) -> DBOccurrenceResult:
    """Convert MCP OccurrenceResult to DB representation."""
    return DBOccurrenceResult(
        tp_id=str(result.tp_id),
        occurrence_id=result.occurrence_id,
        found_credit=result.found_credit,
        matched_by=[_occurrence_match_to_db(m) for m in result.matched_by],
        rationale=str(result.rationale),
    )


def _unknown_issue_to_db(unknown: UnknownIssue) -> DBUnknownIssue:
    """Convert MCP UnknownIssue to DB representation."""
    return DBUnknownIssue(id=str(unknown.input_id), rationale=str(unknown.rationale))


def grader_success_to_db(success: GraderSuccess) -> DBGraderSuccess:
    """Convert MCP GraderSuccess to DB representation."""
    return DBGraderSuccess(
        tag="success",
        occurrence_results=[_occurrence_result_to_db(r) for r in success.occurrence_results],
        unknowns=[_unknown_issue_to_db(u) for u in success.unknowns],
        summary=str(success.summary),
    )


def grader_output_to_db(output: GraderOutput) -> DBGraderOutput:
    """Convert MCP GraderOutput (discriminated union) to DB representation."""
    if isinstance(output, GraderSuccess):
        return grader_success_to_db(output)
    if isinstance(output, GraderMaxTurnsExceeded):
        return DBGraderMaxTurnsExceeded(tag="max_turns_exceeded", max_turns=output.max_turns)
    raise TypeError(f"Unexpected GraderOutput variant: {type(output)}")
