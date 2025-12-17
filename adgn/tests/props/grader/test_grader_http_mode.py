"""Test grader agent with HTTP MCP mode (MCP-over-HTTP with bearer token auth).

Tests the new HTTP transport for grader_submit tools using real Docker containers,
real PostgreSQL database, and mocked OpenAI responses.
"""

from __future__ import annotations

import importlib

import pytest

from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.config import get_database_config
from adgn.props.db.models import CriticRunStatus, GraderRun, GraderRunStatus
from adgn.props.grader.grader import grade_critic_run_by_id
from tests.llm.support.openai_mock import CapturingOpenAIModel
from tests.support.responses import ResponsesFactory

# Using fixtures from conftest.py:
# - test_snapshot: snapshot slug
# - test_prompt_sha: critic prompt hash
# - subtract_file_scope: ExplicitFileScope for subtract.py
# - zero_issues_critic_responses: configured critic client


def _make_grader_response_sequence() -> list:
    """Create response sequence for grader that grades a zero-issue critique."""
    factory = ResponsesFactory("gpt-5-nano")

    # In HTTP mode, the agent directly calls the grader_submit MCP tool
    # (not via docker_exec with a Python script)
    return [
        # 1. Call grader_submit tool (in HTTP mode this goes to the HTTP MCP server)
        factory.make(factory.tool_call("grader_submit", {"summary": "Zero issues submitted, nothing to grade."}))
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_grader_http_mode_zero_issues(
    monkeypatch,
    synced_test_fixtures,
    test_trivial_specimen,
    make_openai_client,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    zero_issues_critic_responses,
    async_docker_client,
    test_specimens_hydrator,
):
    """Test grader successfully grades zero-issue critique using HTTP MCP mode.

    This tests the MCP-over-HTTP transport with:
    - Real Docker container
    - Real PostgreSQL database
    - Mocked OpenAI responses
    - HTTP MCP server with bearer token auth
    """
    # Enable HTTP mode via environment variable
    monkeypatch.setenv("ADGN_USE_MCP_HTTP", "1")

    # Need to reload the module to pick up the environment variable
    from adgn.props.grader import grader as grader_module

    importlib.reload(grader_module)

    # Step 1: Run critic to create a critique with zero issues
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

    # Step 2: Run grader with HTTP mode enabled (via USE_MCP_HTTP env var)
    base_client = make_openai_client(_make_grader_response_sequence())
    grader_client = CapturingOpenAIModel(base_client)
    db_config = get_database_config()

    with get_session() as session:
        try:
            grader_run_id = await grade_critic_run_by_id(
                session=session,
                critic_run_id=critic_run_id,
                client=grader_client,
                docker_client=async_docker_client,
                hydrator=test_specimens_hydrator,
                db_config=db_config,
                prompt_optimization_run_id=None,
                verbose=False,
                max_turns=100,
            )

            assert grader_run_id is not None

            # Verify database records
            session.commit()  # Ensure changes are committed
            grader_run = session.get(GraderRun, grader_run_id)
            assert grader_run is not None
            assert grader_run.snapshot_slug == test_snapshot
            assert grader_run.critic_run_id == critic_run_id

            # Verify the grader completed successfully
            assert grader_run.status == GraderRunStatus.COMPLETED, f"Expected COMPLETED, got {grader_run.status}"
            # Note: output field is deprecated (nullable), use grading_decisions table for results
        except (RuntimeError, AssertionError):
            # Print captured requests for debugging
            print(f"\n=== Captured {len(grader_client.captured)} requests ===")
            for i, req in enumerate(grader_client.captured):
                print(f"\n--- Request {i + 1} ---")
                # req.input is list[InputItem] | str, where InputItem is a union of Pydantic message types
                if isinstance(req.input, list):
                    for msg in req.input:
                        # msg is InputItem (Pydantic model)
                        msg_dict = msg.model_dump()
                        role = msg_dict.get("role", str(type(msg).__name__))
                        content_preview = str(msg_dict)[:200]
                        print(f"  {role}: {content_preview}")
                elif isinstance(req.input, str):
                    print(f"  (string input): {req.input[:200]}")
            raise


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_grader_http_mode_environment_variable(
    synced_test_fixtures,
    test_trivial_specimen,
    make_openai_client,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    zero_issues_critic_responses,
    async_docker_client,
    test_specimens_hydrator,
):
    """Test grader HTTP mode via ADGN_USE_MCP_HTTP environment variable.

    Verifies that setting ADGN_USE_MCP_HTTP=1 enables HTTP mode.
    """
    # Create critic output first
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

    # Run grader (should use HTTP mode from environment)
    grader_client = make_openai_client(_make_grader_response_sequence())

    with get_session() as session:
        grader_run_id = await grade_critic_run_by_id(
            session=session,
            critic_run_id=critic_run_id,
            client=grader_client,
            docker_client=async_docker_client,
            hydrator=test_specimens_hydrator,
            db_config=synced_test_fixtures,
            prompt_optimization_run_id=None,
            verbose=False,
            max_turns=100,
        )

        assert grader_run_id is not None

        # Verify the grader completed successfully
        session.commit()
        grader_run = session.get(GraderRun, grader_run_id)
        assert grader_run is not None
        assert grader_run.status == GraderRunStatus.COMPLETED
