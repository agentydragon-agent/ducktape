"""E2E tests for critic agent with HTTP MCP mode.

Tests the critic agent end-to-end using:
- Real Docker containers
- Real PostgreSQL database with temporary RLS-scoped users
- Mocked OpenAI responses
- HTTP MCP transport with bearer token auth

Covers:
- Zero issues submission (clean code)
- Issue submission workflow
- Infinite loop prevention (regression test)
"""

from __future__ import annotations

from props_core.db.agent_definition_ids import CRITIC_AGENT_DEFINITION_ID
from props_core.db.models import AgentRun, AgentRunStatus, Event
from props_core.db.session import get_session
import pytest

from agent_core.events import ApiRequest, SystemText, ToolCall
from agent_core.testing import AssertDockerExecThenCall, DockerExecCall, Step


def _make_critic_steps_zero_issues_minimal() -> list[Step]:
    """Create minimal step sequence for critic that finds zero issues.

    Uses critique CLI to submit directly (fastest path).
    """
    return [DockerExecCall(cmd=["critique", "submit", "0", "Reviewed code, no issues found"], timeout_ms=15000)]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_http_mode_zero_issues(run_critic_with_steps, test_snapshot):
    """Test critic successfully submits zero issues using HTTP MCP mode.

    This tests the MCP-over-HTTP transport with:
    - Real Docker container
    - Real PostgreSQL database with temporary RLS-scoped user (critic_agent_{run_id})
    - Mocked OpenAI responses
    - HTTP MCP server with bearer token auth
    """
    critic_run_id, status, _runner = await run_critic_with_steps(_make_critic_steps_zero_issues_minimal())

    # Verify status
    assert status == AgentRunStatus.COMPLETED, "Critic should succeed in HTTP mode"
    assert critic_run_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(AgentRun, critic_run_id)
        assert run is not None
        assert run.critic_config().example.snapshot_slug == test_snapshot
        assert run.status == AgentRunStatus.COMPLETED
        # Check issues in normalized tables (not JSONB)
        assert len(run.reported_issues) == 0

        # Verify events were persisted (DatabaseEventHandler stores events by agent_run_id)
        events = session.query(Event).filter_by(agent_run_id=critic_run_id).order_by(Event.sequence_num).all()
        assert len(events) > 0, "Expected at least one event to be persisted"

        # Check for api_request events (OpenAI calls)
        api_request_events = [e for e in events if isinstance(e.payload, ApiRequest)]
        assert len(api_request_events) >= 1, "Expected at least one api_request event"

        # Check for tool_call events (the submit call)
        tool_call_events = [e for e in events if isinstance(e.payload, ToolCall)]
        assert len(tool_call_events) >= 1, "Expected at least one tool_call event"

        # Check for system_text event (init script output)
        system_text_events = [e for e in events if isinstance(e.payload, SystemText)]
        assert len(system_text_events) == 1, "Expected exactly one system_text event"
        assert system_text_events[0].sequence_num == 0, "System text should be first event (sequence 0)"


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_does_not_infinite_loop_on_zero_issues(run_critic_with_steps):
    """Verify critic doesn't get stuck in infinite loop when finding zero issues.

    Regression test: Before the fix, RequireAnyTool() would force dummy docker_exec
    calls indefinitely. After the fix, the agent uses CLI helpers to submit and
    terminates properly.

    This test verifies the agent can successfully complete without unnecessary exploratory calls.
    """
    _critic_run_id, status, runner = await run_critic_with_steps(_make_critic_steps_zero_issues_minimal())

    assert status == AgentRunStatus.COMPLETED, "Critic should succeed"
    # Step runner validates via bootstrap check; verify single step was used
    assert runner.current_step_index == 1, f"Expected 1 step completed, got {runner.current_step_index}"


def _make_critic_steps_with_issues() -> list[Step]:
    """Create step sequence for critic that finds and submits issues.

    Uses critique CLI which runs INSIDE THE CONTAINER where it has access
    to the RLS-scoped credentials set up by the agent environment.
    """
    return [
        # 1. Insert issue using critique CLI (agent_run_id auto-detected from env)
        DockerExecCall(
            cmd=["critique", "insert-issue", "dead-import", "Unused import detected in subtract.py"], timeout_ms=15000
        ),
        # 2. Insert occurrence with file location
        AssertDockerExecThenCall(
            expected_output="",  # Just check exit code 0
            next_cmd=["critique", "insert-occurrence", "dead-import", "subtract.py", "-s", "1", "-e", "1"],
            timeout_ms=15000,
        ),
        # 3. Submit via critique CLI
        AssertDockerExecThenCall(
            expected_output="",  # Just check exit code 0
            next_cmd=["critique", "submit", "1", "Found 1 dead code issue"],
            timeout_ms=15000,
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_http_mode_submit_with_issues(run_critic_with_steps, test_snapshot):
    """Test critic HTTP mode with actual issue submission.

    Verifies that the critic can:
    1. Write issues to database using RLS-scoped credentials from container env
    2. Submit via MCP HTTP server with correct file path validation
    """
    critic_run_id, status, _runner = await run_critic_with_steps(_make_critic_steps_with_issues())

    # Verify status
    assert status == AgentRunStatus.COMPLETED, "Critic should succeed in HTTP mode with issues"
    assert critic_run_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(AgentRun, critic_run_id)
        assert run is not None
        assert run.critic_config().example.snapshot_slug == test_snapshot
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


def _make_critic_steps_zero_issues() -> list[Step]:
    """Create step sequence for run_critic that finds zero issues.

    Uses the AgentHandle-based infrastructure which loads system prompt
    from the /init script output.
    """
    return [DockerExecCall(cmd=["critique", "submit", "0", "No issues found"], timeout_ms=15000)]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_zero_issues(run_critic_with_steps, test_snapshot):
    """Test run_critic with AgentHandle-based flow.

    Tests the package-based flow that uses:
    - AgentHandle to load agent package from database
    - /init script output as the system prompt
    - CriticAgentEnvironment for temp user and MCP server
    """
    critic_run_id, status, _runner = await run_critic_with_steps(_make_critic_steps_zero_issues())

    # Verify status
    assert status == AgentRunStatus.COMPLETED, "Critic should succeed"
    assert critic_run_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(AgentRun, critic_run_id)
        assert run is not None
        assert run.critic_config().example.snapshot_slug == test_snapshot
        assert run.status == AgentRunStatus.COMPLETED
        # Definition ID is stored in agent_definition_id
        assert run.agent_definition_id == CRITIC_AGENT_DEFINITION_ID
        # Check issues in normalized tables
        assert len(run.reported_issues) == 0
