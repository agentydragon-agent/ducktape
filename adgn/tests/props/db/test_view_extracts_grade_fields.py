"""Test that the occurrence_credits view correctly extracts fields from GraderOutput."""

from uuid import uuid4

from sqlalchemy import text

from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentRunStatus, TruePositive
from adgn.props.grader.models import GraderSuccess, InputIssueID, OccurrenceMatch, OccurrenceResult, TruePositiveID
from adgn.props.ids import SnapshotSlug
from adgn.props.rationale import Rationale
from tests.conftest import EMPTY_CANONICAL_ISSUES_SNAPSHOT
from tests.props.conftest import make_critic_run, make_grader_run, make_reported_issues, populate_grading_decisions


def test_view_extracts_grade_fields_correctly(synced_test_db: DatabaseConfig):
    """Test that the view includes grader runs with occurrence-based results.

    Uses git-synced test fixtures (test-fixtures/test-trivial) instead of synthetic data.
    The test-trivial fixture has a TP 'test-issue' with occurrence 'occ-1' in subtract.py.
    """
    # Use git-synced fixture: test-fixtures/test-trivial (TRAIN split)
    snapshot_slug = SnapshotSlug("test-fixtures/test-trivial")
    critic_agent_run_id = uuid4()
    grader_agent_run_id = uuid4()

    with get_session() as session:
        # Get an existing example from git fixtures - use any single-file-set example
        example = (
            session.query(Example).filter_by(snapshot_slug=snapshot_slug).filter(Example.files_hash.isnot(None)).first()
        )
        assert example is not None, "Expected a single-file-set example in test-trivial"

        # Get the actual TP from the fixture to match against
        tps = session.query(TruePositive).filter_by(snapshot_slug=snapshot_slug).all()
        # The test-trivial fixture has test-issue with occ-1 in subtract.py
        # Find the TP that has subtract.py in its occurrences
        matching_tp = None
        matching_occ_id = None
        for tp in tps:
            for occ in tp.occurrences:
                if "subtract.py" in [str(f) for f in occ.files]:
                    matching_tp = tp
                    matching_occ_id = occ.occurrence_id
                    break
            if matching_tp:
                break

        assert matching_tp is not None, "Should find a TP with subtract.py"
        assert matching_occ_id is not None

        # Create GraderSuccess with occurrence results matching the git fixture TP
        grader_success = GraderSuccess(
            occurrence_results=[
                OccurrenceResult(
                    tp_id=TruePositiveID(matching_tp.tp_id),
                    occurrence_id=matching_occ_id,
                    found_credit=1.0,
                    matched_by=[OccurrenceMatch(input_id=InputIssueID("input-test-001"), credit=1.0)],
                    rationale=Rationale("Fully found this occurrence"),
                )
            ],
            summary=Rationale("Test grading summary"),
        )

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
        assert result.tp_id == matching_tp.tp_id, "Should extract tp_id from occurrence_results"
        assert result.occurrence_id == matching_occ_id, "Should extract occurrence_id from occurrence_results"
        assert result.found_credit == 1.0, "Should extract found_credit from occurrence_results"
