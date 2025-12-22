"""Test that the occurrence_credits view correctly extracts fields from GraderOutput."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentRunStatus, Snapshot, TruePositive
from adgn.props.grader.models import GraderSuccess, InputIssueID, OccurrenceMatch, OccurrenceResult, TruePositiveID
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import ExplicitFileScope
from adgn.props.models.snapshot import LocalSource
from adgn.props.models.true_positive import TruePositiveOccurrence
from adgn.props.rationale import Rationale
from adgn.props.splits import Split
from tests.conftest import EMPTY_CANONICAL_ISSUES_SNAPSHOT
from tests.props.conftest import make_critic_run, make_grader_run, make_reported_issues, populate_grading_decisions


def test_view_extracts_grade_fields_correctly(synced_test_db):
    """Test that the view includes grader runs with occurrence-based results."""

    # Create test data
    snapshot_slug = SnapshotSlug("test-view/2025-01-01-00")
    critic_agent_run_id = uuid4()
    grader_agent_run_id = uuid4()

    # Scope for the critic run
    files = ["test/file1.py", "test/file2.py"]
    scope = ExplicitFileScope(files=files)

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

    with get_session() as session:
        # Insert snapshot
        snapshot = Snapshot(slug=snapshot_slug, split=Split.VALID, source=LocalSource(vcs="local", root="."))
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
        example = Example.from_scope(snapshot_slug, scope)
        session.add(example)
        session.flush()

        # Insert critic run (required for view join) using fixture factory
        critic_run = make_critic_run(example=example, agent_run_id=critic_agent_run_id, status=AgentRunStatus.COMPLETED)
        session.add(critic_run)
        session.flush()

        # Create reported issues first (required for grading decisions FK)
        issue_ids = ["input-test-001"]  # From the match in occurrence_results
        make_reported_issues(agent_run_id=critic_run.agent_run_id, issue_ids=issue_ids, session=session)

        # Insert grader run with output using fixture factory
        grader_run = make_grader_run(
            critic_run=critic_run,
            canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
            model="test-grader-model",
            agent_run_id=grader_agent_run_id,
        )
        session.add(grader_run)
        session.flush()  # Ensure grader_run.agent_run_id is available

        # Populate grading_decisions table from MCP occurrence_results
        populate_grading_decisions(
            grader_run=grader_run, occurrence_results=grader_success.occurrence_results, session=session
        )

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
        assert result.grader_run_id == grader_run.agent_run_id, "Should match the grader run ID"
        assert result.tp_id == "tp-test-001", "Should extract tp_id from occurrence_results"
        assert result.occurrence_id == "occ-1", "Should extract occurrence_id from occurrence_results"
        assert result.found_credit == 1.0, "Should extract found_credit from occurrence_results"
