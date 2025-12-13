"""Test that the valid_metrics view correctly extracts fields from GraderOutput."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Critique, Example, GraderRun, Snapshot, TruePositive
from adgn.props.grader.models import (
    CanonicalTPCoverage,
    GradeSubmitInput,
    InputIssueID,
    IssueCoverageEntry,
    ReportedIssueRatios,
    TPCoverageEntry,
    TruePositiveID,
)
from adgn.props.grader.persistence import grade_submit_input_to_db
from adgn.props.ids import SnapshotSlug
from adgn.props.models.true_positive import TruePositiveOccurrence
from tests.conftest import EMPTY_CANONICAL_ISSUES_SNAPSHOT


def test_view_extracts_grade_fields_correctly(test_db, test_prompt_sha):
    """Test that the view extracts recall and other fields from GraderOutput."""

    # Create test data
    snapshot_slug = SnapshotSlug("test-view/2025-01-01-00")
    critic_transcript_id = uuid4()
    grader_transcript_id = uuid4()
    critique_id = uuid4()

    # Files for the critic run
    files = ["test/file1.py", "test/file2.py"]
    files_hash = hashlib.sha256("\n".join(sorted(files)).encode()).hexdigest()

    # Create a GradeSubmitInput with the actual schema
    grade = GradeSubmitInput(
        canonical_tp_coverage=[
            TPCoverageEntry(
                canonical_id=TruePositiveID("tp-test-001"),
                coverage=CanonicalTPCoverage(
                    covered_by=[IssueCoverageEntry(input_id=InputIssueID("input-test-001"), credit=1.0)],
                    recall_credit=1.0,
                    rationale="Fully covered",
                ),
            )
        ],
        canonical_fp_coverage=[],
        novel_critique_issues=[],
        reported_issue_ratios=ReportedIssueRatios(tp=1.0, fp=0.0, unlabeled=0.0),
        recall=0.75,  # 75% recall
        summary="Test grading",
    )

    # Convert to DB format
    grader_output_db = grade_submit_input_to_db(grade)

    with get_session() as session:
        # Insert snapshot
        snapshot = Snapshot(slug=snapshot_slug, split="valid")
        session.add(snapshot)

        # Insert TruePositive records (required for snapshot_files_with_issues view)
        tp1 = TruePositive(
            snapshot_slug=snapshot_slug,
            tp_id="test-tp-001",
            rationale="Test issue in file1",
            occurrences=[
                TruePositiveOccurrence(
                    files={Path("test/file1.py"): None},
                    expect_caught_from={frozenset([Path("test/file1.py")])},
                    note=None,
                )
            ],
        )
        session.add(tp1)

        tp2 = TruePositive(
            snapshot_slug=snapshot_slug,
            tp_id="test-tp-002",
            rationale="Test issue in file2",
            occurrences=[
                TruePositiveOccurrence(
                    files={Path("test/file2.py"): None},
                    expect_caught_from={frozenset([Path("test/file2.py")])},
                    note=None,
                )
            ],
        )
        session.add(tp2)

        # Insert example (required for valid_metrics view join)
        example = Example(snapshot_slug=snapshot_slug, files=files, files_hash=files_hash)
        session.add(example)

        # Insert critique (required FK for grader_run)
        critique_payload = CriticSubmitPayload(issues=[], notes_md=None)
        critique = Critique(id=critique_id, snapshot_slug=snapshot_slug, payload=critique_payload)
        session.add(critique)

        # Insert critic run (required for view join)
        critic_run = CriticRun(
            transcript_id=critic_transcript_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-critic-model",
            critique_id=critique_id,
            files=files,
            files_hash=files_hash,
            output={},
        )
        session.add(critic_run)

        # Insert grader run with output
        grader_run = GraderRun(
            transcript_id=grader_transcript_id,
            snapshot_slug=snapshot_slug,
            critique_id=critique_id,
            model="test-grader-model",
            canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
            output=grader_output_db,
        )
        session.add(grader_run)
        session.commit()

        # Query the view
        result = session.execute(
            text("""
                SELECT recall
                FROM valid_metrics
                WHERE snapshot_slug = :slug
            """),
            {"slug": str(snapshot_slug)},
        ).fetchone()

        assert result is not None, "View should return a row"

        # Check recall is extracted correctly
        assert result.recall == pytest.approx(0.75), f"Expected recall=0.75, got {result.recall}"
