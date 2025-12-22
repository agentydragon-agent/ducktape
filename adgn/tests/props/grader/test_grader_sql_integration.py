"""Integration test for grader SQL workflow.

Tests the end-to-end SQL workflow where grader agents:
1. Get temporary database credentials with RLS scoping
2. Write grading decisions directly to PostgreSQL
3. Call grader_submit tool to finalize grading
4. Validation occurs on submit (ensures all input issues have decisions)
"""

from __future__ import annotations

from fastmcp.exceptions import ToolError
import pytest
from sqlalchemy import create_engine, text

from adgn.props.db import get_session
from adgn.props.db.models import AgentRun, AgentRunStatus, GradingDecision, ReportedIssue
from adgn.props.db.temp_user_manager import TempUserManager
from adgn.props.grader.submit_server import GraderSubmitServer
from tests.props.grader.conftest import make_test_grader_run

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@pytest.fixture
async def grader_temp_creds(test_db, test_grader_run):
    """Create temporary database user with RLS scoping."""
    async with TempUserManager(test_db.admin, test_grader_run) as creds:
        yield creds


@pytest.fixture
def temp_grader_engine(test_db, grader_temp_creds):
    """Create SQLAlchemy engine with temp grader credentials."""
    user_config = test_db.admin.with_user(grader_temp_creds)
    engine = create_engine(user_config.url())
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def grader_submit_server(test_grader_run, test_grader_critic_run):
    """Create grader submit server."""
    return GraderSubmitServer(grader_run_id=test_grader_run, critic_run_id=test_grader_critic_run)


async def test_grader_sql_basic_workflow(grader_submit_server, test_grader_run, test_db, temp_grader_engine):
    """Test basic grader SQL workflow with TP, FP, and no-match decisions."""
    # Simulate agent actions using temp user credentials

    with temp_grader_engine.connect() as conn:
        # Decision 1: TP match
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, target_tp_id, target_tp_occurrence_id,
                   credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :tp_id, :occ_id, :credit, :rationale)
            """),
            {
                "input_id": "input-001",
                "tp_id": "tp-001",
                "occ_id": "occ-001",
                "credit": 0.8,
                "rationale": "Matches TP occurrence partially",
            },
        )

        # Decision 2: FP match
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, target_fp_id, target_fp_occurrence_id,
                   credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :fp_id, :occ_id, :credit, :rationale)
            """),
            {
                "input_id": "input-002",
                "fp_id": "fp-001",
                "occ_id": "occ-fp-001",
                "credit": 1.0,
                "rationale": "Matches known FP pattern",
            },
        )

        # Decision 3: No-match
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
            """),
            {"input_id": "input-003", "credit": 0.0, "rationale": "No matching ground truth"},
        )

        conn.commit()

    # Agent calls submit tool
    tool_result = await grader_submit_server.submit_tool.run(
        {"summary": "Graded 3 input issues: 1 TP, 1 FP, 1 no-match"}
    )

    # Verify result
    result = tool_result.structured_content
    assert result["message"] == "Grading completed successfully with 3 decisions"
    assert result["decisions_count"] == 3
    assert result["input_issues_count"] == 3

    # Verify database state
    with get_session() as session:
        # Check decisions exist
        decisions = session.query(GradingDecision).filter_by(agent_run_id=test_grader_run).all()
        assert len(decisions) == 3

        tp_decision = next(d for d in decisions if d.input_issue_id == "input-001")
        assert tp_decision.target_tp_id == "tp-001"
        assert tp_decision.target_tp_occurrence_id == "occ-001"
        assert tp_decision.credit == 0.8

        fp_decision = next(d for d in decisions if d.input_issue_id == "input-002")
        assert fp_decision.target_fp_id == "fp-001"
        assert fp_decision.target_fp_occurrence_id == "occ-fp-001"
        assert fp_decision.credit == 1.0

        no_match = next(d for d in decisions if d.input_issue_id == "input-003")
        assert no_match.target_tp_id is None
        assert no_match.target_fp_id is None
        assert no_match.credit == 0.0


async def test_grader_sql_missing_decision_fails(grader_submit_server, test_grader_run, test_db, temp_grader_engine):
    """Test submit fails if any input issue lacks a decision."""
    with temp_grader_engine.connect() as conn:
        # Only create decisions for 2 out of 3 input issues
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
            """),
            {"input_id": "input-001", "credit": 0.0, "rationale": "No match"},
        )

        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
            """),
            {"input_id": "input-002", "credit": 0.0, "rationale": "No match"},
        )

        # Missing decision for input-003!
        conn.commit()

    # Submit should FAIL
    with pytest.raises(ToolError, match="Missing grading decisions for input issues: input-003"):
        await grader_submit_server.submit_tool.run({"summary": "Incomplete grading"})


async def test_grader_sql_multiple_decisions_allowed(
    grader_submit_server, test_grader_run, test_db, temp_grader_engine
):
    """Test that multiple decisions per input issue are allowed (partial credit to multiple TPs)."""

    with temp_grader_engine.connect() as conn:
        # Create valid decisions for input-001 and input-002
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
            """),
            {"input_id": "input-001", "credit": 0.0, "rationale": "No match"},
        )

        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
            """),
            {"input_id": "input-002", "credit": 0.0, "rationale": "No match"},
        )

        # Create TWO decisions for input-003 (partial matches to different TPs)
        # This is allowed: one input can match multiple ground truth issues with partial credit
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, target_tp_id, target_tp_occurrence_id,
                   credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :tp_id, :occ_id, :credit, :rationale)
            """),
            {
                "input_id": "input-003",
                "tp_id": "tp-001",
                "occ_id": "occ-001",
                "credit": 0.3,
                "rationale": "Partially matches tp-001",
            },
        )

        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, target_tp_id, target_tp_occurrence_id,
                   credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :tp_id, :occ_id, :credit, :rationale)
            """),
            {
                "input_id": "input-003",
                "tp_id": "tp-002",
                "occ_id": "occ-002",
                "credit": 0.5,
                "rationale": "Also partially matches tp-002",
            },
        )

        conn.commit()

    # Submit should SUCCEED - multiple decisions per input are allowed
    tool_result = await grader_submit_server.submit_tool.run({"summary": "Multiple decisions allowed"})

    # Verify result
    result = tool_result.structured_content
    assert result["message"] == "Grading completed successfully with 4 decisions"
    assert result["decisions_count"] == 4  # 4 total decisions (1+1+2)
    assert result["input_issues_count"] == 3


async def test_grader_sql_rls_isolation(
    test_grader_run, test_grader_critic_run, test_snapshot, test_db, temp_grader_engine
):
    """Test RLS isolation - agents can only see their own run's decisions."""
    # Create another grader run (different agent)
    other_run_id = make_test_grader_run(test_snapshot, test_grader_critic_run)

    # Insert decision from other run (using admin credentials)
    # First, add the input issues to reported_issues (required by check constraint)
    with get_session() as session:
        # Add "other-input" to the critic run's reported issues (for other grader run)
        other_issue = ReportedIssue(
            agent_run_id=test_grader_critic_run, issue_id="other-input", rationale="Other issue"
        )
        session.add(other_issue)

        # Add "my-input" to the critic run's reported issues (for test_grader_run via temp creds)
        my_issue = ReportedIssue(agent_run_id=test_grader_critic_run, issue_id="my-input", rationale="My issue")
        session.add(my_issue)

        session.flush()

        # Now add the decision for other run
        decision = GradingDecision(
            agent_run_id=other_run_id, input_issue_id="other-input", credit=0.0, rationale="Other agent's decision"
        )
        session.add(decision)
        session.commit()

    # Now agent with temp_creds inserts their own decision

    with temp_grader_engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
            """),
            {"input_id": "my-input", "credit": 0.0, "rationale": "My decision"},
        )
        conn.commit()

        # Query should only see own run's data
        result = conn.execute(text("SELECT input_issue_id FROM grading_decisions ORDER BY input_issue_id"))
        input_ids = [row[0] for row in result]

        # Should ONLY see "my-input", not "other-input"
        assert input_ids == ["my-input"]


async def test_grader_sql_credit_sum_trigger_enforcement(
    test_grader_run, test_grader_critic_run, test_db, temp_grader_engine
):
    """Test SQL trigger prevents credit sum > 1.0 for same TP occurrence."""
    with temp_grader_engine.connect() as conn:
        # Decision for input-001: 0.7 credit to tp-shared/occ-shared
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, target_tp_id, target_tp_occurrence_id,
                   credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :tp_id, :occ_id, :credit, :rationale)
            """),
            {
                "input_id": "input-001",
                "tp_id": "tp-shared",
                "occ_id": "occ-shared",
                "credit": 0.7,
                "rationale": "First match",
            },
        )
        conn.commit()

        # Decision for input-002: 0.5 credit to SAME tp-shared/occ-shared (total 1.2 > 1.0)
        # SQL trigger should REJECT this immediately on execute
        with pytest.raises(Exception, match=r"Credit sum would exceed 1\.0"):
            conn.execute(
                text("""
                    INSERT INTO grading_decisions
                      (agent_run_id, input_issue_id, target_tp_id, target_tp_occurrence_id,
                       credit, rationale)
                    VALUES (current_agent_run_id(), :input_id, :tp_id, :occ_id, :credit, :rationale)
                """),
                {
                    "input_id": "input-002",
                    "tp_id": "tp-shared",
                    "occ_id": "occ-shared",
                    "credit": 0.5,
                    "rationale": "Second match (would exceed 1.0)",
                },
            )


async def test_grader_sql_hard_delete_revision_workflow(
    grader_submit_server, test_grader_run, test_db, temp_grader_engine
):
    """Test hard delete workflow - delete incorrect decision and replace with new one."""
    with temp_grader_engine.connect() as conn:
        # Create active decisions for all 3 input issues
        for i in range(1, 4):
            conn.execute(
                text("""
                    INSERT INTO grading_decisions
                      (agent_run_id, input_issue_id, credit, rationale)
                    VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
                """),
                {"input_id": f"input-00{i}", "credit": 0.0, "rationale": f"Decision {i}"},
            )

        # Hard delete decision for input-002 (agent reconsidered)
        conn.execute(
            text("""
                DELETE FROM grading_decisions
                WHERE agent_run_id = current_agent_run_id()
                  AND input_issue_id = :input_id
            """),
            {"input_id": "input-002"},
        )

        conn.commit()

    # Submit should require a NEW decision for input-002 (deleted one doesn't count)
    with pytest.raises(ToolError, match="Missing grading decisions for input issues: input-002"):
        await grader_submit_server.submit_tool.run({"summary": "Missing decision due to deletion"})

    # Now create new active decision for input-002

    with temp_grader_engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO grading_decisions
                  (agent_run_id, input_issue_id, credit, rationale)
                VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
            """),
            {"input_id": "input-002", "credit": 0.0, "rationale": "Revised decision"},
        )
        conn.commit()

    # Now submit should succeed
    tool_result = await grader_submit_server.submit_tool.run({"summary": "All decisions finalized (1 revised)"})

    result = tool_result.structured_content
    assert result["decisions_count"] == 3  # 3 active decisions
    assert result["input_issues_count"] == 3


# =============================================================================
# Report Failure Tool Tests
# =============================================================================


async def test_grader_report_failure_basic(grader_submit_server, test_grader_run, test_db):
    """Test report_failure tool marks run as failed with reason."""
    # Call report_failure tool
    await grader_submit_server.report_failure_tool.run(
        {"message": "Cannot grade: critic output is malformed and contains no parseable issues"}
    )

    # Verify database state
    with get_session() as session:
        grader_run = session.get(AgentRun, test_grader_run)
        assert grader_run is not None
        assert grader_run.status == AgentRunStatus.REPORTED_FAILURE
        assert (
            grader_run.completion_summary == "Cannot grade: critic output is malformed and contains no parseable issues"
        )


async def test_grader_report_failure_prevents_subsequent_submit(
    grader_submit_server, test_grader_run, test_db, temp_grader_engine
):
    """Test that submit fails after report_failure has been called."""
    # First report failure
    await grader_submit_server.report_failure_tool.run({"message": "Grading not possible"})

    # Then try to submit - should fail because run already reported failure
    with pytest.raises(ToolError, match="already reported failure"):
        await grader_submit_server.submit_tool.run({"summary": "Attempting late submit"})


async def test_grader_report_failure_after_complete_fails(
    grader_submit_server, test_grader_run, test_db, temp_grader_engine
):
    """Test that report_failure fails if run is already completed."""
    # First complete the run by adding decisions and submitting
    with temp_grader_engine.connect() as conn:
        for i in range(1, 4):
            conn.execute(
                text("""
                    INSERT INTO grading_decisions
                      (agent_run_id, input_issue_id, credit, rationale)
                    VALUES (current_agent_run_id(), :input_id, :credit, :rationale)
                """),
                {"input_id": f"input-00{i}", "credit": 0.0, "rationale": f"Decision {i}"},
            )
        conn.commit()

    # Submit successfully
    await grader_submit_server.submit_tool.run({"summary": "Completed grading"})

    # Then try to report failure - should fail because already completed
    with pytest.raises(ToolError, match="already completed"):
        await grader_submit_server.report_failure_tool.run({"message": "Trying to fail after completion"})


async def test_grader_report_failure_idempotency_fails(grader_submit_server, test_grader_run, test_db):
    """Test that calling report_failure twice fails (not idempotent)."""
    # First call succeeds
    await grader_submit_server.report_failure_tool.run({"message": "First failure report"})

    # Second call should fail
    with pytest.raises(ToolError, match="already reported failure"):
        await grader_submit_server.report_failure_tool.run({"message": "Second failure report"})
