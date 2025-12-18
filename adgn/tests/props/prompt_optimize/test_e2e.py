"""Prompt optimizer e2e tests.

Tests the prompt optimizer agent using:
- Real Docker containers
- Real PostgreSQL database with temporary RLS-scoped users
- Mocked OpenAI responses
- HTTP MCP transport with bearer token auth
"""

from __future__ import annotations

import pytest

from adgn.props.db.config import DatabaseConfig
from adgn.props.prompt_optimize.prompt_optimizer import run_prompt_optimizer
from adgn.props.prompt_optimize.target_metric import TargetMetric
from adgn.props.runs_context import RunsContext
from tests.support.steps import AssertDockerExecThenCall, DockerExecCallWithBootstrapValidation

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@pytest.mark.timeout(30)
@pytest.mark.requires_docker
async def test_po_agent_psql_connectivity(
    synced_test_fixtures: DatabaseConfig,
    tmp_path,
    make_openai_client,
    test_specimens_hydrator,
    async_docker_client,
    make_step_runner,
):
    """Test that psql works from the agent container using PG* env vars.

    Verifies that:
    1. Bootstrap commands completed successfully (validates container setup)
    2. The container has access to psql
    3. PG* environment variables (PGHOST, PGPORT, etc.) are correctly injected
    4. Container can reach postgres via Docker network
    5. psql respects the PG* env vars and connects without explicit arguments
    """
    # Define test steps using step runner pattern
    # First step validates bootstrap succeeded, then executes psql connectivity check
    steps = [
        # Step 0: Validate bootstrap succeeded, then check psql connectivity
        DockerExecCallWithBootstrapValidation(cmd=["psql", "-Atc", "SELECT 1"], timeout_ms=30000),
        # Step 1: Assert psql returned "1", then call report-failure to terminate
        AssertDockerExecThenCall(
            expected_output="1",
            next_cmd=[
                "adgn-properties",
                "agent-helper",
                "optimizer",
                "report-failure",
                "Test completed: psql connectivity verified",
            ],
            timeout_ms=30000,
        ),
    ]

    # Create step runner - implements OpenAIModelProto directly
    runner = make_step_runner(steps=steps)

    # Critic and grader won't be invoked (empty list will fail if called)
    critic_client = make_openai_client([])
    grader_client = make_openai_client([])

    await run_prompt_optimizer(
        budget=1.0,
        ctx=RunsContext.from_pkg_dir(),
        hydrator=test_specimens_hydrator,
        optimizer_client=runner,
        critic_client=critic_client,
        grader_client=grader_client,
        docker_client=async_docker_client,
        out_dir=tmp_path,
        target_metric=TargetMetric.WHOLE_REPO,
        db_config=synced_test_fixtures,
    )
