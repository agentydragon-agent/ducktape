"""E2E tests for critic agent with HTTP MCP mode.

Tests the critic agent end-to-end using:
- Real Docker containers
- Real PostgreSQL database with temporary RLS-scoped users
- Mocked OpenAI responses
- HTTP MCP transport with bearer token auth

Covers:
- Zero issues submission (clean code)
- Issue submission workflow
- Bootstrap script connection
- Infinite loop prevention (regression test)
"""

from __future__ import annotations

from uuid import uuid4

from fastmcp.client import Client
import pytest

from adgn.props.agent_setup import make_mcp_http_bootstrap_script
from adgn.props.critic.critic import (
    CRITIC_SCOPE_RESOURCE_URI,
    CRITIC_SNAPSHOT_SLUG_RESOURCE_URI,
    CriticAgentEnvironment,
    run_critic,
)
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, CriticRunStatus
from tests.support.steps import AssertDockerExecThenCall, DockerExecCallWithBootstrapValidation, Step


def _make_critic_steps_zero_issues_minimal() -> list[Step]:
    """Create minimal step sequence for critic that finds zero issues.

    Uses CLI helper to submit directly (fastest path).
    First step validates bootstrap succeeded.
    """
    return [
        # Submit via CLI helper (no issues to add) - also validates bootstrap
        DockerExecCallWithBootstrapValidation(
            cmd=["adgn-properties", "agent-helper", "critic", "submit", "0", "Reviewed code, no issues found"],
            timeout_ms=15000,
        )
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_http_mode_zero_issues(
    synced_test_db,
    test_trivial_specimen,
    make_step_runner,
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
    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_critic_steps_zero_issues_minimal())

    # Run critic with HTTP mode enabled
    input_data = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    critic_run_id, status = await run_critic(
        input_data=input_data,
        client=runner,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        mount_properties=False,
        max_turns=100,
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
async def test_critic_does_not_infinite_loop_on_zero_issues(
    synced_test_db,
    test_trivial_specimen,
    make_step_runner,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
):
    """Verify critic doesn't get stuck in infinite loop when finding zero issues.

    Regression test: Before the fix, RequireAnyTool() would force dummy docker_exec
    calls indefinitely. After the fix, the agent uses CLI helpers to submit and
    terminates properly.

    This test verifies the agent can successfully complete without unnecessary exploratory calls.
    """
    # Use step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_critic_steps_zero_issues_minimal())

    input_data = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    _, status = await run_critic(
        input_data=input_data,
        client=runner,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        mount_properties=False,
        max_turns=100,
    )

    assert status == CriticRunStatus.COMPLETED, "Critic should succeed"
    # Step runner validates via bootstrap check; verify single step was used
    assert runner.current_step_index == 1, f"Expected 1 step completed, got {runner.current_step_index}"


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_http_bootstrap_connection(
    synced_test_db,
    test_trivial_specimen,
    test_snapshot,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
):
    """Test that bootstrap script can connect to MCP server and list tools.

    Verifies the MCP-over-HTTP bootstrap works by:
    1. Starting a critic environment with HTTP server
    2. Running the actual bootstrap script (same one used by AgentEnvironment)
    3. Checking output contains expected tool names
    """
    # Create critic environment (starts HTTP server)
    critic_run_id = uuid4()
    critic_env = CriticAgentEnvironment(
        snapshot_slug=test_snapshot,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        critic_run_id=critic_run_id,
        scope=subtract_file_scope,
        db_config=synced_test_db,
        mount_properties=False,
    )

    async with critic_env as compositor:
        # Generate the actual bootstrap script that AgentEnvironment uses
        bootstrap_script = make_mcp_http_bootstrap_script(
            resources=[("Snapshot Slug", CRITIC_SNAPSHOT_SLUG_RESOURCE_URI), ("Scope", CRITIC_SCOPE_RESOURCE_URI)]
        )

        # Execute bootstrap script by calling the exec tool via MCP client
        async with Client(compositor.runtime.server) as client:
            tool_result = await client.call_tool(
                "exec",
                {
                    "cmd": ["python3", "-c", bootstrap_script],
                    "cwd": None,
                    "env": None,
                    "user": None,
                    "timeout_ms": 15_000,
                },
            )

        # Parse output from MCP tool result
        assert not tool_result.is_error, f"Tool call failed: {tool_result.content}"
        result = tool_result.structured_content

        # Verify execution succeeded
        assert isinstance(result, dict), f"Expected dict result, got: {type(result)}"
        assert "exit" in result, f"No 'exit' key in result: {list(result.keys())}"
        exit_info = result["exit"]
        assert exit_info.get("exit_code") == 0, (
            f"Bootstrap failed (exit {exit_info.get('exit_code')})\nstderr: {result.get('stderr', '')}\nstdout: {result.get('stdout', '')}"
        )

        stdout = result.get("stdout", "")

        # Verify MCP server initialization succeeded
        assert "MCP Server Initialization" in stdout, "Failed to initialize MCP session"

        # Verify tools were listed
        assert "Available Tools" in stdout, "Failed to list tools section"

        # Verify expected critic tools are present (HTTP mode uses submit-only flow)
        expected_tools = ["submit", "report_failure"]
        for tool_name in expected_tools:
            assert tool_name in stdout, f"Expected tool '{tool_name}' not found in bootstrap output"

        # Verify resources were read with actual content
        assert "Snapshot Slug" in stdout, "Failed to read snapshot slug resource header"
        assert test_snapshot in stdout, f"Expected snapshot slug '{test_snapshot}' not found in resource content"

        assert "Scope" in stdout, "Failed to read scope resource header"
        # Scope should contain the file from subtract_file_scope
        assert "subtract.py" in stdout, "Expected scope file 'subtract.py' not found in resource content"


def _make_critic_steps_with_issues() -> list[Step]:
    """Create step sequence for critic that finds and submits issues.

    Uses CLI helper commands which run INSIDE THE CONTAINER where they have access
    to the RLS-scoped credentials set up by the agent environment.
    First step validates bootstrap succeeded.
    """
    return [
        # 1. Add issue using CLI helper (critic_run_id auto-detected from env)
        # Also validates bootstrap on first step
        DockerExecCallWithBootstrapValidation(
            cmd=[
                "adgn-properties",
                "agent-helper",
                "critic",
                "add-issue",
                "dead-import",
                "Unused import detected in subtract.py",
            ],
            timeout_ms=15000,
        ),
        # 2. Add occurrence with file location
        AssertDockerExecThenCall(
            expected_output="",  # Just check exit code 0
            next_cmd=[
                "adgn-properties",
                "agent-helper",
                "critic",
                "add-occurrence",
                "dead-import",
                "subtract.py",
                "-s",
                "1",
                "-e",
                "1",
            ],
            timeout_ms=15000,
        ),
        # 3. Submit via CLI helper
        AssertDockerExecThenCall(
            expected_output="",  # Just check exit code 0
            next_cmd=["adgn-properties", "agent-helper", "critic", "submit", "1", "Found 1 dead code issue"],
            timeout_ms=15000,
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_http_mode_submit_with_issues(
    synced_test_db,
    test_trivial_specimen,
    make_step_runner,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
):
    """Test critic HTTP mode with actual issue submission.

    Verifies that the critic can:
    1. Write issues to database using RLS-scoped credentials from container env
    2. Submit via MCP HTTP server with correct file path validation
    """
    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_critic_steps_with_issues())

    input_data = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    # Run critic - bootstrap validation happens on first step
    critic_run_id, status = await run_critic(
        input_data=input_data,
        client=runner,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        mount_properties=False,
        max_turns=100,
    )

    # Verify status
    assert status == CriticRunStatus.COMPLETED, "Critic should succeed in HTTP mode with issues"
    assert critic_run_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(CriticRun, critic_run_id)
        assert run is not None
        assert run.snapshot_slug == test_snapshot
        assert run.status == CriticRunStatus.COMPLETED

        # Check that the issue was actually stored
        assert len(run.reported_issues) == 1
        issue = run.reported_issues[0]
        assert issue.issue_id == "dead-import"
        assert "Unused import" in issue.rationale

        # Check occurrence
        assert len(issue.occurrences) == 1
        occurrence = issue.occurrences[0]
        assert len(occurrence.locations) == 1
        assert occurrence.locations[0].file == "subtract.py"
