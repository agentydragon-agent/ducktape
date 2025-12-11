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
    DBFPCoverageEntry,
    DBGraderOutput,
    DBIssueCoverageEntry,
    DBKnownFalsePositive,
    DBLineRange,
    DBNovelIssueEntry,
    DBNovelIssueReasoning,
    DBReportedIssueRatios,
    DBTPCoverageEntry,
    DBTruePositiveIssue,
    DBTruePositiveOccurrence,
)
from adgn.props.grader.models import (
    CanonicalFPCoverage,
    CanonicalTPCoverage,
    FalsePositiveID,
    GradeSubmitInput,
    InputIssueID,
    IssueCoverageEntry,
    KnownFalsePositive,
    TruePositiveID,
    TruePositiveIssue,
)
from adgn.props.models.true_positive import FalsePositiveOccurrence, LineRange, TruePositiveOccurrence
from adgn.props.rationale import Rationale


def _convert_line_range_to_db(lr: LineRange) -> DBLineRange:
    """Convert MCP LineRange to DB representation."""
    return DBLineRange(start_line=lr.start_line, end_line=lr.end_line)


def _convert_line_range_from_db(db_lr: DBLineRange) -> LineRange:
    """Convert DB LineRange to MCP representation."""
    return LineRange(start_line=db_lr.start_line, end_line=db_lr.end_line)


def tp_to_db(tp: TruePositiveIssue) -> DBTruePositiveIssue:
    """Convert MCP TruePositiveIssue to DB representation."""
    return DBTruePositiveIssue(
        id=str(tp.id),
        rationale=str(tp.rationale),
        occurrences=[
            DBTruePositiveOccurrence(
                files={
                    str(path): [_convert_line_range_to_db(lr) for lr in ranges] if ranges else None
                    for path, ranges in occ.files.items()
                },
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
                files={
                    Path(path): [_convert_line_range_from_db(lr) for lr in ranges] if ranges else None
                    for path, ranges in occ.files.items()
                },
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
                files={
                    str(path): [_convert_line_range_to_db(lr) for lr in ranges] if ranges else None
                    for path, ranges in occ.files.items()
                },
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
                files={
                    Path(path): [_convert_line_range_from_db(lr) for lr in ranges] if ranges else None
                    for path, ranges in occ.files.items()
                },
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
    from adgn.props.rationale import Rationale

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
    from adgn.props.rationale import Rationale

    return CanonicalFPCoverage(
        covered_by=[InputIssueID(id) for id in db_coverage.covered_by], rationale=Rationale(db_coverage.rationale)
    )


def grade_submit_input_to_db(grade: GradeSubmitInput) -> DBGraderOutput:
    """Convert MCP GradeSubmitInput to DB representation."""
    return DBGraderOutput(
        canonical_tp_coverage=[
            DBTPCoverageEntry(
                canonical_id=str(entry.canonical_id), coverage=_canonical_tp_coverage_to_db(entry.coverage)
            )
            for entry in grade.canonical_tp_coverage
        ],
        canonical_fp_coverage=[
            DBFPCoverageEntry(
                canonical_id=str(entry.canonical_id), coverage=_canonical_fp_coverage_to_db(entry.coverage)
            )
            for entry in grade.canonical_fp_coverage
        ],
        novel_critique_issues=[
            DBNovelIssueEntry(
                input_id=str(entry.input_id), reasoning=DBNovelIssueReasoning(rationale=str(entry.reasoning.rationale))
            )
            for entry in grade.novel_critique_issues
        ],
        reported_issue_ratios=(
            DBReportedIssueRatios(
                tp=grade.reported_issue_ratios.tp,
                fp=grade.reported_issue_ratios.fp,
                unlabeled=grade.reported_issue_ratios.unlabeled,
            )
            if grade.reported_issue_ratios
            else None
        ),
        recall=grade.recall,
        summary=str(grade.summary),
    )
