"""E2E tests for critic agent with HTTP MCP mode.

Tests the critic agent end-to-end using:
- Real Docker containers
- Real PostgreSQL database with temporary RLS-scoped users
- Mocked OpenAI responses
- HTTP MCP transport with bearer token auth

Covers:
- Zero issues submission (clean code)
- Issue submission workflow
- Bootstrap ./init script execution (validated via DockerExecCallWithBootstrapValidation)
- Infinite loop prevention (regression test)

All tests verify that bootstrap commands (including ./init) exit with code 0
before proceeding with the test scenario.
"""

from __future__ import annotations

import pytest

from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.critic.critic import run_critic
from adgn.props.db import get_session
from adgn.props.db.models import AgentRun, AgentRunStatus, Event
from tests.support.steps import AssertDockerExecThenCall, DockerExecCallWithBootstrapValidation, Step


def _make_critic_steps_zero_issues_minimal() -> list[Step]:
    """Create minimal step sequence for critic that finds zero issues.

    Uses /workspace/bin/critique CLI to submit directly (fastest path).
    First step validates bootstrap succeeded.
    """
    return [
        # Submit via critique CLI (no issues to add) - also validates bootstrap
        DockerExecCallWithBootstrapValidation(
            cmd=["python", "/workspace/bin/critique.py", "submit", "0", "Reviewed code, no issues found"],
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
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
    tmp_path,
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

    # Create workspace manager pointing to temp path
    workspace_manager = WorkspaceManager(tmp_path)

    # Run critic using AgentHandle-based flow
    critic_run_id, status = await run_critic(
        definition_id="critic",
        snapshot_slug=test_snapshot,
        scope=subtract_file_scope,
        client=runner,
        parent_agent_run_id=None,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        workspace_manager=workspace_manager,
        mount_properties=False,
        max_turns=100,
    )

    # Verify status
    assert status == AgentRunStatus.COMPLETED, "Critic should succeed in HTTP mode"
    assert critic_run_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(AgentRun, critic_run_id)
        assert run is not None
        assert run.critic_config().snapshot_slug == test_snapshot
        assert run.status == AgentRunStatus.COMPLETED
        # Check issues in normalized tables (not JSONB)
        assert len(run.reported_issues) == 0

        # Verify events were persisted (DatabaseEventHandler stores events by agent_run_id)
        events = session.query(Event).filter_by(agent_run_id=critic_run_id).order_by(Event.sequence_num).all()
        assert len(events) > 0, "Expected at least one event to be persisted"

        # Check for api_request events (OpenAI calls)
        api_request_events = [e for e in events if e.event_type == "api_request"]
        assert len(api_request_events) >= 1, "Expected at least one api_request event"

        # Check for tool_call events (the submit call)
        tool_call_events = [e for e in events if e.event_type == "tool_call"]
        assert len(tool_call_events) >= 1, "Expected at least one tool_call event"


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_does_not_infinite_loop_on_zero_issues(
    synced_test_db,
    test_trivial_specimen,
    make_step_runner,
    test_snapshot,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
    tmp_path,
):
    """Verify critic doesn't get stuck in infinite loop when finding zero issues.

    Regression test: Before the fix, RequireAnyTool() would force dummy docker_exec
    calls indefinitely. After the fix, the agent uses CLI helpers to submit and
    terminates properly.

    This test verifies the agent can successfully complete without unnecessary exploratory calls.
    """
    # Use step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_critic_steps_zero_issues_minimal())

    # Create workspace manager pointing to temp path
    workspace_manager = WorkspaceManager(tmp_path)

    _, status = await run_critic(
        definition_id="critic",
        snapshot_slug=test_snapshot,
        scope=subtract_file_scope,
        client=runner,
        parent_agent_run_id=None,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        workspace_manager=workspace_manager,
        mount_properties=False,
        max_turns=100,
    )

    assert status == AgentRunStatus.COMPLETED, "Critic should succeed"
    # Step runner validates via bootstrap check; verify single step was used
    assert runner.current_step_index == 1, f"Expected 1 step completed, got {runner.current_step_index}"


def _make_critic_steps_with_issues() -> list[Step]:
    """Create step sequence for critic that finds and submits issues.

    Uses /workspace/bin/critique.py CLI which runs INSIDE THE CONTAINER where it has access
    to the RLS-scoped credentials set up by the agent environment.
    First step validates bootstrap succeeded.
    """
    return [
        # 1. Insert issue using critique CLI (agent_run_id auto-detected from env)
        # Also validates bootstrap on first step
        DockerExecCallWithBootstrapValidation(
            cmd=[
                "python",
                "/workspace/bin/critique.py",
                "insert-issue",
                "dead-import",
                "Unused import detected in subtract.py",
            ],
            timeout_ms=15000,
        ),
        # 2. Insert occurrence with file location
        AssertDockerExecThenCall(
            expected_output="",  # Just check exit code 0
            next_cmd=[
                "python",
                "/workspace/bin/critique.py",
                "insert-occurrence",
                "dead-import",
                "subtract.py",
                "-s",
                "1",
                "-e",
                "1",
            ],
            timeout_ms=15000,
        ),
        # 3. Submit via critique CLI
        AssertDockerExecThenCall(
            expected_output="",  # Just check exit code 0
            next_cmd=["python", "/workspace/bin/critique.py", "submit", "1", "Found 1 dead code issue"],
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
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
    tmp_path,
):
    """Test critic HTTP mode with actual issue submission.

    Verifies that the critic can:
    1. Write issues to database using RLS-scoped credentials from container env
    2. Submit via MCP HTTP server with correct file path validation
    """
    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_critic_steps_with_issues())

    # Create workspace manager pointing to temp path
    workspace_manager = WorkspaceManager(tmp_path)

    # Run critic - bootstrap validation happens on first step
    critic_run_id, status = await run_critic(
        definition_id="critic",
        snapshot_slug=test_snapshot,
        scope=subtract_file_scope,
        client=runner,
        parent_agent_run_id=None,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        workspace_manager=workspace_manager,
        mount_properties=False,
        max_turns=100,
    )

    # Verify status
    assert status == AgentRunStatus.COMPLETED, "Critic should succeed in HTTP mode with issues"
    assert critic_run_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(AgentRun, critic_run_id)
        assert run is not None
        assert run.critic_config().snapshot_slug == test_snapshot
        assert run.status == AgentRunStatus.COMPLETED

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


# =============================================================================
# AgentHandle-based flow tests (run_critic)
# =============================================================================


def _make_critic_v2_steps_zero_issues() -> list[Step]:
    """Create step sequence for run_critic that finds zero issues.

    Uses the AgentHandle-based infrastructure which loads system prompt
    from AGENT.md in the definition.
    """
    return [
        # Submit via critique CLI (no issues to add) - validates bootstrap worked
        DockerExecCallWithBootstrapValidation(
            cmd=["python", "/workspace/bin/critique.py", "submit", "0", "No issues found"], timeout_ms=15000
        )
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_v2_zero_issues(
    synced_test_db,
    test_trivial_specimen,
    make_step_runner,
    test_snapshot,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
    tmp_path,
):
    """Test run_critic with AgentHandle-based flow.

    Tests the definition-based flow that uses:
    - AgentHandle to load agent definition from database
    - AGENT.md as the system prompt (no Jinja rendering)
    - init script for bootstrap context injection
    - Same CriticAgentEnvironment for temp user and MCP server
    """
    # Create step runner with bootstrap validation
    runner = make_step_runner(steps=_make_critic_v2_steps_zero_issues())

    # Create workspace manager pointing to temp path
    workspace_manager = WorkspaceManager(tmp_path)

    # Run critic using AgentHandle-based flow
    critic_run_id, status = await run_critic(
        definition_id="critic",  # The base critic definition
        snapshot_slug=test_snapshot,
        scope=subtract_file_scope,
        client=runner,
        parent_agent_run_id=None,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_db,
        workspace_manager=workspace_manager,
        mount_properties=False,
        max_turns=100,
    )

    # Verify status
    assert status == AgentRunStatus.COMPLETED, "Critic v2 should succeed"
    assert critic_run_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(AgentRun, critic_run_id)
        assert run is not None
        assert run.critic_config().snapshot_slug == test_snapshot
        assert run.status == AgentRunStatus.COMPLETED
        # Definition ID is stored in agent_definition_id
        assert run.agent_definition_id == "critic"
        # Check issues in normalized tables
        assert len(run.reported_issues) == 0
