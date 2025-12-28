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

from props_core.db.models import AgentRun, AgentRunStatus, GradingEdge
from props_core.db.session import get_session
import pytest

from agent_core.testing import AssertDockerExecThenCall, CapturingOpenAIModel, DockerExecCall, Step


def _make_critic_steps_zero_issues() -> list[Step]:
    """Create minimal step sequence for critic that finds zero issues."""
    return [DockerExecCall(cmd=["critique", "submit", "0", "Reviewed code, no issues found"], timeout_ms=15000)]


@pytest.fixture
async def zero_issue_critic_run(run_critic_with_steps):
    """Create a zero-issue critic run for grader testing."""
    critic_run_id, status, _runner = await run_critic_with_steps(_make_critic_steps_zero_issues())
    assert status == AgentRunStatus.COMPLETED
    assert critic_run_id is not None
    return critic_run_id


def _make_grader_steps() -> list[Step]:
    """Create step sequence for grader that grades via CLI + HTTP finalization.

    Uses bin CLI commands which run INSIDE THE CONTAINER where they have access
    to the RLS-scoped credentials set up by the agent environment.
    """
    return [
        # For zero-issue critique: no input issues to grade, just submit via CLI
        DockerExecCall(
            cmd=["grade", "submit", "Graded zero-issue critique against ground truth. No issues to match."],
            timeout_ms=15000,
        )
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_grader_http_mode_zero_issues(zero_issue_critic_run, make_step_runner, test_snapshot, test_registry):
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

    try:
        grader_run_id = await test_registry.run_grader(
            critic_run_id=zero_issue_critic_run, client=grader_client, max_turns=100
        )

        assert grader_run_id is not None

        # Verify database records
        with get_session() as session:
            grader_run = session.get(AgentRun, grader_run_id)
            assert grader_run is not None
            # For graders, snapshot_slug is derived from the graded critic's type_config
            grader_config = grader_run.grader_config()
            graded_critic = session.get(AgentRun, grader_config.graded_agent_run_id)
            assert graded_critic is not None
            assert graded_critic.critic_config().example.snapshot_slug == test_snapshot
            assert grader_config.graded_agent_run_id == zero_issue_critic_run

            # Verify the grader completed successfully
            assert grader_run.status == AgentRunStatus.COMPLETED, f"Expected COMPLETED, got {grader_run.status}"
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
async def test_grader_http_mode_sql_workflow(zero_issue_critic_run, make_step_runner, test_registry):
    """Test grader HTTP mode with SQL workflow.

    Verifies that the agent can execute Python code that:
    1. Writes grading decisions directly to PostgreSQL
    2. Makes HTTP request to finalize via grader_submit(summary="...")
    """
    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_grader_steps())

    grader_run_id = await test_registry.run_grader(critic_run_id=zero_issue_critic_run, client=runner, max_turns=100)

    assert grader_run_id is not None

    with get_session() as session:
        grader_run = session.get(AgentRun, grader_run_id)
        assert grader_run is not None
        assert grader_run.status == AgentRunStatus.COMPLETED


# =============================================================================
# Comprehensive Data Access Test
# =============================================================================


def _make_critic_steps_with_issue() -> list[Step]:
    """Create step sequence for critic that submits one issue.

    Uses bin CLI commands which run INSIDE THE CONTAINER where they have access
    to the RLS-scoped credentials set up by the agent environment.
    """
    return [
        # 1. Add issue using bin CLI
        DockerExecCall(cmd=["critique", "insert-issue", "test-issue-01", "Test issue found in code"], timeout_ms=15000),
        # 2. Add occurrence with file location
        AssertDockerExecThenCall(
            expected_output="",
            next_cmd=["critique", "insert-occurrence", "test-issue-01", "subtract.py", "-s", "1", "-e", "5"],
            timeout_ms=15000,
        ),
        # 3. Submit via bin CLI
        AssertDockerExecThenCall(
            expected_output="", next_cmd=["critique", "submit", "1", "Found 1 test issue"], timeout_ms=15000
        ),
    ]


@pytest.fixture
async def critic_run_with_issue(run_critic_with_steps):
    """Create a critic run with one reported issue for grader testing."""
    critic_run_id, status, _runner = await run_critic_with_steps(_make_critic_steps_with_issue())
    assert status == AgentRunStatus.COMPLETED, f"Expected COMPLETED, got {status}"
    assert critic_run_id is not None

    # Verify the issue was actually created
    with get_session() as session:
        critic_run = session.get(AgentRun, critic_run_id)
        assert critic_run is not None
        assert len(critic_run.reported_issues) == 1, f"Expected 1 issue, got {len(critic_run.reported_issues)}"

    return critic_run_id


def _make_grader_steps_comprehensive(critic_run_id: str, fp_id: str) -> list[Step]:
    """Create step sequence for grader that demonstrates full data access.

    Steps demonstrate that the grader agent can:
    1. Read critic runs (query reported_issues from the critique being graded)
    2. Read ground truth (query true_positives, false_positives)
    3. Write grading decisions
    4. Submit via MCP

    Uses psql queries to verify database access, then bin CLI for decisions.

    Args:
        critic_run_id: UUID of the critic run to grade
        fp_id: Expected FP ID from the git fixtures (use fp_id pytest fixture)
    """
    return [
        # Step 1: Read reported_issues from the critique being graded
        # This demonstrates grader can access critic run data
        DockerExecCall(
            cmd=[
                "psql",
                "-c",
                f"SELECT issue_id, rationale FROM reported_issues WHERE agent_run_id = '{critic_run_id}'",
            ],
            timeout_ms=2000,
        ),
        # Step 2: Read true_positives for this snapshot
        # This demonstrates grader can access ground truth TPs
        # test-fixtures/train1 has TP "test-issue" catchable from subtract.py
        AssertDockerExecThenCall(
            expected_output="test-issue-01",  # Reported issue from critic
            next_cmd=["psql", "-c", "SELECT tp_id, rationale FROM true_positives LIMIT 5"],
            timeout_ms=2000,
        ),
        # Step 3: Read false_positives for this snapshot
        # This demonstrates grader can access ground truth FPs
        # test-fixtures/train1 has a FP defined in git fixtures
        AssertDockerExecThenCall(
            expected_output="test-issue",  # TP ID from fixture
            next_cmd=["psql", "-c", "SELECT fp_id, rationale FROM false_positives LIMIT 5"],
            timeout_ms=2000,
        ),
        # Step 4: Add a no-match decision for the reported issue
        # This demonstrates grader can write grading decisions
        # Step 3's FP query returns the FP from git fixtures
        AssertDockerExecThenCall(
            expected_output=fp_id,  # FP ID from git fixtures (via pytest fixture)
            next_cmd=["grade", "add-no-match", "test-issue-01", "Novel finding not in canonical ground truth"],
            timeout_ms=10000,
        ),
        # Step 5: Submit grading via bin CLI (which calls MCP)
        AssertDockerExecThenCall(
            expected_output="Added no-match decision",
            next_cmd=["grade", "submit", "Graded 1 issue: 1 novel finding (no canonical match)"],
            timeout_ms=10000,
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
@pytest.mark.timeout(60)  # Critic fixture + grader steps (~48s observed)
async def test_grader_comprehensive_data_access(
    critic_run_with_issue, make_step_runner, test_snapshot, test_registry, fp_id
):
    """Test grader can read critic runs, ground truth, write decisions, and submit.

    This comprehensive test verifies that the grader agent has proper RLS-scoped
    access to:
    1. reported_issues table (read critique being graded)
    2. true_positives table (read ground truth TPs)
    3. false_positives table (read ground truth FPs)
    4. grading_edges table (write edges via CLI helper)
    5. MCP submit endpoint (finalize grading)

    The test uses psql queries to demonstrate direct database access works,
    then uses CLI helpers to write decisions and submit.
    """
    # Create step runner with comprehensive steps
    # fp_id comes from pytest fixture (queries git-synced test fixtures)
    runner = make_step_runner(steps=_make_grader_steps_comprehensive(str(critic_run_with_issue), fp_id))
    grader_client = CapturingOpenAIModel(runner)

    try:
        grader_run_id = await test_registry.run_grader(
            critic_run_id=critic_run_with_issue, client=grader_client, max_turns=100
        )

        assert grader_run_id is not None

        # Verify database records
        with get_session() as session:
            grader_run = session.get(AgentRun, grader_run_id)
            assert grader_run is not None
            # For graders, snapshot_slug is derived from the graded critic's type_config
            grader_config2 = grader_run.grader_config()
            graded_critic = session.get(AgentRun, grader_config2.graded_agent_run_id)
            assert graded_critic is not None
            assert graded_critic.critic_config().example.snapshot_slug == test_snapshot
            assert grader_config2.graded_agent_run_id == critic_run_with_issue

            # Verify the grader completed successfully
            assert grader_run.status == AgentRunStatus.COMPLETED, f"Expected COMPLETED, got {grader_run.status}"

            # Verify grading edge was written
            edges = session.query(GradingEdge).filter(GradingEdge.grader_run_id == grader_run_id).all()
            assert len(edges) == 1, f"Expected 1 edge, got {len(edges)}"
            edge = edges[0]
            assert edge.critique_issue_id == "test-issue-01"
            assert edge.tp_id is None  # no-match edge has NULL tp_id
            assert edge.fp_id is None  # no-match edge has NULL fp_id

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
