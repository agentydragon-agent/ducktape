"""Test critic agent with HTTP MCP mode (MCP-over-HTTP with bearer token auth).

Tests the new HTTP transport for critic_submit tools using real Docker containers,
real PostgreSQL database, mocked OpenAI responses, and temporary PostgreSQL users
with RLS scoping.
"""

from __future__ import annotations

import importlib

import pytest

from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, CriticRunStatus
from tests.support.responses import ResponsesFactory

# Simple clean code that should have zero issues
TRIVIAL_CLEAN_CODE = '''#!/usr/bin/env python3
"""A trivial script that subtracts two numbers."""


def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    return a - b


def main() -> None:
    """Main entry point."""
    print("Enter two numbers to subtract:")
    try:
        num1 = float(input("First number: "))
        num2 = float(input("Second number: "))
        result = subtract(num1, num2)
        print(f"{num1} - {num2} = {result}")
    except ValueError:
        print("Error: Please enter valid numbers")
        return


if __name__ == "__main__":
    main()
'''


def _make_critic_response_sequence() -> list:
    """Create response sequence for critic that finds zero issues."""
    factory = ResponsesFactory("gpt-5-nano")

    # Python script that agent will execute to call the HTTP MCP submit tool
    submit_script = """
import asyncio
from adgn.props.agent_helpers import mcp_client_from_env

async def submit_critique():
    async with mcp_client_from_env() as (session, init_result):
        result = await session.call_tool("submit", {"issues_count": 0, "summary": "Reviewed code, no issues found"})
        if result.isError:
            print(f"Submit failed: {result.content}")
        else:
            print(f"Submit succeeded: {result.structuredContent}")

asyncio.run(submit_critique())
"""

    return [
        # 1. Read the Python file
        factory.make(factory.docker_exec(["cat", "/workspace/subtract.py"], timeout_ms=5000)),
        # 2. Execute Python to connect to HTTP server and call submit
        factory.make(factory.docker_exec(["python3", "-c", submit_script], timeout_ms=15000)),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_http_mode_zero_issues(
    synced_test_fixtures,
    test_trivial_specimen,
    make_openai_client,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
):
    """Test critic successfully submits zero issues using HTTP MCP mode.

    This tests the MCP-over-HTTP transport with:
    - Real Docker container
    - Real PostgreSQL database with temporary RLS-scoped user (critic_agent_{run_id})
    - Mocked OpenAI responses
    - HTTP MCP server with bearer token auth
    """
    # Create fake OpenAI client with expected tool call sequence
    client = make_openai_client(_make_critic_response_sequence())

    # Run critic with HTTP mode enabled
    input_data = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    critic_run_id, status = await run_critic(
        input_data=input_data,
        client=client,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_fixtures,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        mount_properties=False,
        max_turns=100,
        http_mode=True,  # ← Enable HTTP MCP transport with temp RLS user
    )

    # Verify status
    assert status == CriticRunStatus.COMPLETED, "Critic should succeed in HTTP mode"
    assert critic_run_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(CriticRun, critic_run_id)
        assert run is not None
        assert run.snapshot_slug == test_snapshot
        assert run.status == CriticRunStatus.COMPLETED
        # Check issues in normalized tables (not JSONB)
        assert len(run.reported_issues) == 0


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_http_mode_environment_variable(
    synced_test_fixtures,
    test_trivial_specimen,
    make_openai_client,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
    monkeypatch,
):
    """Test critic HTTP mode via ADGN_USE_MCP_HTTP environment variable.

    Verifies that setting ADGN_USE_MCP_HTTP=1 enables HTTP mode with temporary
    RLS-scoped PostgreSQL users.
    """
    # Set environment variable
    monkeypatch.setenv("ADGN_USE_MCP_HTTP", "1")

    # Need to reload the module to pick up the environment variable

    from adgn.props.critic import critic as critic_module

    importlib.reload(critic_module)

    # Verify the environment variable was read
    assert critic_module.USE_MCP_HTTP is True

    # Create fake OpenAI client
    client = make_openai_client(_make_critic_response_sequence())

    input_data = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    # Run critic (should use HTTP mode from environment)
    # Note: The USE_MCP_HTTP env var is read at module load time, so we need to pass http_mode explicitly
    # or the function won't know about the env var change
    _, status = await critic_module.run_critic(
        input_data=input_data,
        client=client,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_fixtures,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        mount_properties=False,
        max_turns=100,
        http_mode=critic_module.USE_MCP_HTTP,  # Pass the reloaded module's value
    )

    assert status == CriticRunStatus.COMPLETED, "Critic should succeed with HTTP mode from environment"
