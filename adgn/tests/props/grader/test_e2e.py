"""Test grader agent with HTTP MCP mode (MCP-over-HTTP with bearer token auth).

Tests the new HTTP transport for grader_submit tools using real Docker containers,
real PostgreSQL database, and mocked OpenAI responses.

Comprehensive tests verify:
- Reading critic runs (reported_issues from the critique being graded)
- Reading ground truth (true_positives, false_positives)
- Writing grading decisions
- Submitting via MCP
"""

from __future__ import annotations

import pytest

from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, CriticRunStatus, GraderRun, GraderRunStatus, GradingDecision
from adgn.props.grader.grader import grade_critic_run_by_id
from tests.llm.support.openai_mock import CapturingOpenAIModel
from tests.support.steps import AssertDockerExecThenCall, DockerExecCallWithBootstrapValidation, Step

# Using fixtures from conftest.py:
# - test_snapshot: snapshot slug
# - test_prompt_sha: critic prompt hash
# - subtract_file_scope: ExplicitFileScope for subtract.py
# - zero_issues_critic_responses: configured critic client


@pytest.fixture
async def zero_issue_critic_run(
    synced_test_db,
    test_trivial_specimen,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    zero_issues_critic_responses,
    async_docker_client,
    test_specimens_hydrator,
):
    """Create a zero-issue critic run for grader testing."""
    critic_input = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    critic_run_id, status = await run_critic(
        input_data=critic_input,
        client=zero_issues_critic_responses,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        max_turns=100,
    )

    assert status == CriticRunStatus.COMPLETED
    assert critic_run_id is not None

    return critic_run_id


def _make_grader_steps() -> list[Step]:
    """Create step sequence for grader that grades via CLI + HTTP finalization.

    Uses CLI helper commands which run INSIDE THE CONTAINER where they have access
    to the RLS-scoped credentials set up by the agent environment.
    First step validates bootstrap succeeded.
    """
    return [
        # For zero-issue critique: no input issues to grade, just submit via CLI
        # Also validates bootstrap on first step
        DockerExecCallWithBootstrapValidation(
            cmd=[
                "adgn-properties",
                "agent-helper",
                "grader",
                "submit",
                "Graded zero-issue critique against ground truth. No issues to match.",
            ],
            timeout_ms=15000,
        )
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_grader_http_mode_zero_issues(
    zero_issue_critic_run, synced_test_db, make_step_runner, test_snapshot, async_docker_client, test_specimens_hydrator
):
    """Test grader successfully grades zero-issue critique using HTTP MCP mode.

    This tests the MCP-over-HTTP transport with:
    - Real Docker container executing Python to make HTTP requests
    - Real PostgreSQL database with SQL workflow
    - Mocked OpenAI responses
    - HTTP MCP server with bearer token auth
    """
    # Create step runner with bootstrap validation - wrap with CapturingOpenAIModel for debugging
    runner = make_step_runner(steps=_make_grader_steps())
    grader_client = CapturingOpenAIModel(runner)

    with get_session() as session:
        try:
            grader_run_id = await grade_critic_run_by_id(
                session=session,
                critic_run_id=zero_issue_critic_run,
                client=grader_client,
                docker_client=async_docker_client,
                hydrator=test_specimens_hydrator,
                db_config=synced_test_db,
                prompt_optimization_run_id=None,
                verbose=False,
                max_turns=100,
            )

            assert grader_run_id is not None

            # Verify database records
            session.commit()
            grader_run = session.get(GraderRun, grader_run_id)
            assert grader_run is not None
            assert grader_run.snapshot_slug == test_snapshot
            assert grader_run.critic_run_id == zero_issue_critic_run

            # Verify the grader completed successfully
            assert grader_run.status == GraderRunStatus.COMPLETED, f"Expected COMPLETED, got {grader_run.status}"
        except (RuntimeError, AssertionError):
            # Print captured requests for debugging
            print(f"\n=== Captured {len(grader_client.captured)} requests ===")
            for i, req in enumerate(grader_client.captured):
                print(f"\n--- Request {i + 1} ---")
                if isinstance(req.input, list):
                    for msg in req.input:
                        msg_dict = msg.model_dump()
                        role = msg_dict.get("role", str(type(msg).__name__))
                        content_preview = str(msg_dict)[:200]
                        print(f"  {role}: {content_preview}")
                elif isinstance(req.input, str):
                    print(f"  (string input): {req.input[:200]}")
            raise


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_grader_http_mode_sql_workflow(
    zero_issue_critic_run, synced_test_db, make_step_runner, async_docker_client, test_specimens_hydrator
):
    """Test grader HTTP mode with SQL workflow.

    Verifies that the agent can execute Python code that:
    1. Writes grading decisions directly to PostgreSQL
    2. Makes HTTP request to finalize via grader_submit(summary="...")
    """
    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_grader_steps())

    with get_session() as session:
        grader_run_id = await grade_critic_run_by_id(
            session=session,
            critic_run_id=zero_issue_critic_run,
            client=runner,
            docker_client=async_docker_client,
            hydrator=test_specimens_hydrator,
            db_config=synced_test_db,
            prompt_optimization_run_id=None,
            verbose=False,
            max_turns=100,
        )

        assert grader_run_id is not None

        session.commit()
        grader_run = session.get(GraderRun, grader_run_id)
        assert grader_run is not None
        assert grader_run.status == GraderRunStatus.COMPLETED


# =============================================================================
# Comprehensive Data Access Test
# =============================================================================


def _make_critic_steps_with_issue() -> list[Step]:
    """Create step sequence for critic that submits one issue.

    Uses CLI helper commands which run INSIDE THE CONTAINER where they have access
    to the RLS-scoped credentials set up by the agent environment.
    """
    return [
        # 1. Add issue using CLI helper - validates bootstrap on first step
        DockerExecCallWithBootstrapValidation(
            cmd=["adgn-properties", "agent-helper", "critic", "add-issue", "test-issue-01", "Test issue found in code"],
            timeout_ms=15000,
        ),
        # 2. Add occurrence with file location
        AssertDockerExecThenCall(
            expected_output="",
            next_cmd=[
                "adgn-properties",
                "agent-helper",
                "critic",
                "add-occurrence",
                "test-issue-01",
                "subtract.py",
                "-s",
                "1",
                "-e",
                "5",
            ],
            timeout_ms=15000,
        ),
        # 3. Submit via CLI helper
        AssertDockerExecThenCall(
            expected_output="",
            next_cmd=["adgn-properties", "agent-helper", "critic", "submit", "1", "Found 1 test issue"],
            timeout_ms=15000,
        ),
    ]


@pytest.fixture
async def critic_run_with_issue(
    synced_test_db,
    test_trivial_specimen,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    make_step_runner,
    async_docker_client,
    test_specimens_hydrator,
):
    """Create a critic run with one reported issue for grader testing."""
    runner = make_step_runner(steps=_make_critic_steps_with_issue())
    critic_input = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    critic_run_id, status = await run_critic(
        input_data=critic_input,
        client=runner,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        mount_properties=False,
        max_turns=100,
    )

    assert status == CriticRunStatus.COMPLETED, f"Expected COMPLETED, got {status}"
    assert critic_run_id is not None

    # Verify the issue was actually created
    with get_session() as session:
        critic_run = session.get(CriticRun, critic_run_id)
        assert critic_run is not None
        assert len(critic_run.reported_issues) == 1, f"Expected 1 issue, got {len(critic_run.reported_issues)}"

    return critic_run_id


def _make_grader_steps_comprehensive(critic_run_id: str) -> list[Step]:
    """Create step sequence for grader that demonstrates full data access.

    Steps demonstrate that the grader agent can:
    1. Read critic runs (query reported_issues from the critique being graded)
    2. Read ground truth (query true_positives, false_positives)
    3. Write grading decisions
    4. Submit via MCP

    Uses psql queries to verify database access, then CLI helpers for decisions.
    """
    return [
        # Step 1: Read reported_issues from the critique being graded
        # This demonstrates grader can access critic run data
        DockerExecCallWithBootstrapValidation(
            cmd=[
                "psql",
                "-c",
                f"SELECT issue_id, rationale FROM reported_issues WHERE critic_run_id = '{critic_run_id}'",
            ],
            timeout_ms=2000,
        ),
        # Step 2: Read true_positives for this snapshot
        # This demonstrates grader can access ground truth TPs
        # test-fixtures/test-trivial has TP "test-issue" catchable from subtract.py
        AssertDockerExecThenCall(
            expected_output="test-issue-01",  # Reported issue from critic
            next_cmd=["psql", "-c", "SELECT tp_id, rationale FROM true_positives LIMIT 5"],
            timeout_ms=2000,
        ),
        # Step 3: Read false_positives for this snapshot
        # test-fixtures/test-trivial has no FPs, so query returns 0 rows
        AssertDockerExecThenCall(
            expected_output="test-issue",  # TP ID from fixture
            next_cmd=["psql", "-c", "SELECT fp_id, rationale FROM false_positives LIMIT 5"],
            timeout_ms=2000,
        ),
        # Step 4: Add a no-match decision for the reported issue
        # This demonstrates grader can write grading decisions
        # Step 3's FP query returns "(0 rows)" since test-trivial has no FPs
        AssertDockerExecThenCall(
            expected_output="(0 rows)",  # No FPs in test-trivial fixture
            next_cmd=[
                "adgn-properties",
                "agent-helper",
                "grader",
                "add-no-match",
                "test-issue-01",
                "Novel finding not in canonical ground truth",
            ],
            timeout_ms=10000,
        ),
        # Step 5: Submit grading via CLI helper (which calls MCP)
        AssertDockerExecThenCall(
            expected_output="Added no-match decision",
            next_cmd=[
                "adgn-properties",
                "agent-helper",
                "grader",
                "submit",
                "Graded 1 issue: 1 novel finding (no canonical match)",
            ],
            timeout_ms=10000,
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
@pytest.mark.timeout(60)  # Critic fixture + grader steps (~48s observed)
async def test_grader_comprehensive_data_access(
    critic_run_with_issue, synced_test_db, make_step_runner, test_snapshot, async_docker_client, test_specimens_hydrator
):
    """Test grader can read critic runs, ground truth, write decisions, and submit.

    This comprehensive test verifies that the grader agent has proper RLS-scoped
    access to:
    1. reported_issues table (read critique being graded)
    2. true_positives table (read ground truth TPs)
    3. false_positives table (read ground truth FPs)
    4. grading_decisions table (write decisions via CLI helper)
    5. MCP submit endpoint (finalize grading)

    The test uses psql queries to demonstrate direct database access works,
    then uses CLI helpers to write decisions and submit.
    """
    # Create step runner with comprehensive steps
    runner = make_step_runner(steps=_make_grader_steps_comprehensive(str(critic_run_with_issue)))
    grader_client = CapturingOpenAIModel(runner)

    with get_session() as session:
        try:
            grader_run_id = await grade_critic_run_by_id(
                session=session,
                critic_run_id=critic_run_with_issue,
                client=grader_client,
                docker_client=async_docker_client,
                hydrator=test_specimens_hydrator,
                db_config=synced_test_db,
                prompt_optimization_run_id=None,
                verbose=False,
                max_turns=100,
            )

            assert grader_run_id is not None

            # Verify database records
            session.commit()
            grader_run = session.get(GraderRun, grader_run_id)
            assert grader_run is not None
            assert grader_run.snapshot_slug == test_snapshot
            assert grader_run.critic_run_id == critic_run_with_issue

            # Verify the grader completed successfully
            assert grader_run.status == GraderRunStatus.COMPLETED, f"Expected COMPLETED, got {grader_run.status}"

            # Verify grading decision was written
            decisions = session.query(GradingDecision).filter(GradingDecision.grader_run_id == grader_run_id).all()
            assert len(decisions) == 1, f"Expected 1 decision, got {len(decisions)}"
            decision = decisions[0]
            assert decision.input_issue_id == "test-issue-01"
            assert decision.target_tp_id is None  # no-match decision has NULL target_tp_id
            assert decision.target_fp_id is None  # no-match decision has NULL target_fp_id

        except (RuntimeError, AssertionError):
            # Print captured requests for debugging
            print(f"\n=== Captured {len(grader_client.captured)} requests ===")
            for i, req in enumerate(grader_client.captured):
                print(f"\n--- Request {i + 1} ---")
                if isinstance(req.input, list):
                    for msg in req.input:
                        msg_dict = msg.model_dump()
                        role = msg_dict.get("role", str(type(msg).__name__))
                        content_preview = str(msg_dict)[:500]
                        print(f"  {role}: {content_preview}")
                elif isinstance(req.input, str):
                    print(f"  (string input): {req.input[:200]}")
            raise
