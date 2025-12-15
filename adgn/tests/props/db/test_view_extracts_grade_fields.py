"""Test that the occurrence_credits view correctly extracts fields from GraderOutput."""

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Critique, Example, GraderRun, Snapshot, TruePositive
from adgn.props.grader.models import GraderSuccess, InputIssueID, OccurrenceMatch, OccurrenceResult, TruePositiveID
from adgn.props.grader.persistence import grader_success_to_db
from adgn.props.ids import SnapshotSlug
from adgn.props.models.snapshot import LocalSource
from adgn.props.models.true_positive import TruePositiveOccurrence
from adgn.props.rationale import Rationale
from tests.conftest import EMPTY_CANONICAL_ISSUES_SNAPSHOT


def test_view_extracts_grade_fields_correctly(test_db, test_prompt_sha):
    """Test that the view includes grader runs with occurrence-based results."""

    # Create test data
    snapshot_slug = SnapshotSlug("test-view/2025-01-01-00")
    critic_transcript_id = uuid4()
    grader_transcript_id = uuid4()
    critique_id = uuid4()

    # Files for the critic run
    files = ["test/file1.py", "test/file2.py"]
    files_hash = hashlib.sha256("\n".join(sorted(files)).encode()).hexdigest()

    # Create GraderSuccess with occurrence results
    grader_success = GraderSuccess(
        occurrence_results=[
            OccurrenceResult(
                tp_id=TruePositiveID("tp-test-001"),
                occurrence_id="occ-1",
                found_credit=1.0,
                matched_by=[OccurrenceMatch(input_id=InputIssueID("input-test-001"), credit=1.0)],
                rationale=Rationale("Fully found this occurrence"),
            )
        ],
        summary=Rationale("Test grading summary"),
    )

    # Convert to DB format
    grader_output_db = grader_success_to_db(grader_success)

    with get_session() as session:
        # Insert snapshot
        snapshot = Snapshot(slug=snapshot_slug, split="valid", source=LocalSource(vcs="local", root="."))
        session.add(snapshot)

        # Insert TruePositive records (required for snapshot_files_with_issues view)
        tp1 = TruePositive(
            snapshot_slug=snapshot_slug,
            tp_id="test-tp-001",
            rationale="Test issue in file1",
            occurrences=[
                TruePositiveOccurrence(
                    occurrence_id="occ-1",
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
                    occurrence_id="occ-2",
                    files={Path("test/file2.py"): None},
                    expect_caught_from={frozenset([Path("test/file2.py")])},
                    note=None,
                )
            ],
        )
        session.add(tp2)

        # Insert example (required for occurrence_credits view join)
        example = Example.file_set(snapshot_slug=snapshot_slug, files=files)
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

        # Query the occurrence_credits view - verify the run appears with occurrence results
        result = session.execute(
            text("""
                SELECT grader_run_id, tp_id, occurrence_id, found_credit
                FROM occurrence_credits
                WHERE snapshot_slug = :slug
            """),
            {"slug": str(snapshot_slug)},
        ).fetchone()

        assert result is not None, "View should return a row for the grader run with occurrence results"
        assert result.grader_run_id == grader_run.id, "Should match the grader run ID"
        assert result.tp_id == "tp-test-001", "Should extract tp_id from occurrence_results"
        assert result.occurrence_id == "occ-1", "Should extract occurrence_id from occurrence_results"
        assert result.found_credit == 1.0, "Should extract found_credit from occurrence_results"
