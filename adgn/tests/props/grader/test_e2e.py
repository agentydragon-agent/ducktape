"""Test grader agent with HTTP MCP mode (MCP-over-HTTP with bearer token auth).

Tests the new HTTP transport for grader_submit tools using real Docker containers,
real PostgreSQL database, and mocked OpenAI responses.
"""

from __future__ import annotations

import pytest

from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.config import get_database_config
from adgn.props.db.models import CriticRunStatus, GraderRun, GraderRunStatus
from adgn.props.grader.grader import grade_critic_run_by_id
from tests.llm.support.openai_mock import CapturingOpenAIModel
from tests.support.steps import DockerExecCallWithBootstrapValidation, Step

# Using fixtures from conftest.py:
# - test_snapshot: snapshot slug
# - test_prompt_sha: critic prompt hash
# - subtract_file_scope: ExplicitFileScope for subtract.py
# - zero_issues_critic_responses: configured critic client


@pytest.fixture
async def zero_issue_critic_run(
    synced_test_fixtures,
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
        db_config=synced_test_fixtures,
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
    zero_issue_critic_run,
    synced_test_fixtures,
    make_step_runner,
    test_snapshot,
    async_docker_client,
    test_specimens_hydrator,
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
                db_config=get_database_config(),
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
    zero_issue_critic_run, synced_test_fixtures, make_step_runner, async_docker_client, test_specimens_hydrator
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
            db_config=synced_test_fixtures,
            prompt_optimization_run_id=None,
            verbose=False,
            max_turns=100,
        )

        assert grader_run_id is not None

        session.commit()
        grader_run = session.get(GraderRun, grader_run_id)
        assert grader_run is not None
        assert grader_run.status == GraderRunStatus.COMPLETED
