"""Test prompt improvement agent end-to-end with mocked OpenAI.

Tests the improvement agent workflow:
- Creating improved package directory via docker_exec
- Submitting via `props agent-pkg create` CLI
- Token budget handling
- RLS-scoped database access
- Termination when package beats baseline average
"""

from __future__ import annotations

from unittest.mock import patch

from hamcrest import contains_string
import pytest

from agent_core.testing.steps import AssertDockerExecThenFinish, DockerExecCall, Step
from props_core.db.agent_definition_ids import CRITIC_AGENT_DEFINITION_ID
from props_core.db.examples import Example
from props_core.db.models import AgentRun
from props_core.db.session import get_session
from props_core.prompt_improve.improve_agent import run_improvement_agent
from props_core.prompt_improve.reminder_handler import BlockingStatus

# Define the improved agent.md content used across tests
# Note: The improvement agent creates a package with Dockerfile + init + agent.md
IMPROVED_AGENT_MD = """# Improved Critic Prompt

You are a code review assistant focused on finding:
1. Dead code (unused imports, unreachable code)
2. Duplication (copy-paste code that should be extracted)
3. Type errors and inconsistencies

Be thorough and systematic in your analysis."""

# Define the init script content
INIT_SCRIPT = """#!/usr/bin/env python3
import sys
from props_core.db.session import get_session
from sqlalchemy import text

with get_session() as session:
    agent_run_id = session.execute(text("SELECT current_agent_run_id()")).scalar()
    if not agent_run_id:
        print("ERROR: current_agent_run_id() is NULL", file=sys.stderr)
        sys.exit(1)
    print(f"Agent run ID: {agent_run_id}")
print("Ready to begin.")
"""


def _make_improvement_steps() -> list[Step]:
    """Create step sequence for improvement agent that creates and submits a package.

    Uses CLI commands which run INSIDE THE CONTAINER where they have access
    to the MCP-over-HTTP server set up by the agent environment.

    The agent:
    1. Creates package directory at /workspace/improved/ via docker_exec
    2. Writes agent.md and init script
    3. Makes init executable
    4. Calls `props agent-pkg create` CLI to submit
    """
    return [
        # 1. Create package directory and write files
        DockerExecCall(
            cmd=[
                "sh",
                "-c",
                f"""mkdir -p /workspace/improved && \
cat > /workspace/improved/agent.md << 'AGENT_EOF'
{IMPROVED_AGENT_MD}
AGENT_EOF
cat > /workspace/improved/init << 'INIT_EOF'
{INIT_SCRIPT}
INIT_EOF
chmod +x /workspace/improved/init""",
            ],
            timeout_ms=15000,
        ),
        # 2. Submit the package via CLI (calls MCP-over-HTTP internally)
        # Note: Uses props agent-pkg create
        # After this, termination check (mocked) returns success so agent finishes
        AssertDockerExecThenFinish(
            expected_output="",  # Just check exit code 0
            message="Package created successfully.",
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_prompt_improve_e2e_success(
    synced_test_db,
    make_step_runner,
    async_docker_client,
    success_termination,
    subtract_file_example,
    noop_openai_client,
):
    """Test improvement agent successfully submits improved definition."""
    runner = make_step_runner(steps=_make_improvement_steps())
    call_count = 0

    def mock_check_termination(session, improvement_run_id, type_config):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return BlockingStatus(message="No definitions created yet.")
        return success_termination

    with patch("props.prompt_improve.reminder_handler.check_termination_condition", side_effect=mock_check_termination):
        result = await run_improvement_agent(
            examples=[subtract_file_example],
            baseline_definition_ids=[CRITIC_AGENT_DEFINITION_ID],
            token_budget=100_000,
            model="gpt-5-nano",
            docker_client=async_docker_client,
            db_config=synced_test_db,
            client=runner,
            critic_client=noop_openai_client,
            grader_client=noop_openai_client,
        )

    assert result.tokens_used >= 0

    with get_session() as session:
        agent_run = session.query(AgentRun).filter_by(agent_run_id=result.run_id).one()
        improvement_config = agent_run.improvement_config()
        assert improvement_config.agent_type == "improvement"
        assert improvement_config.allowed_examples is not None


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_prompt_improve_e2e_multiple_examples(
    synced_test_db, make_step_runner, test_snapshot, async_docker_client, success_termination, noop_openai_client
):
    """Test improvement agent with multiple training examples."""
    with get_session() as session:
        examples = session.query(Example).filter_by(snapshot_slug=test_snapshot).limit(2).all()
        assert len(examples) >= 2, "Need at least 2 examples for this test"
        allowed_examples = [e.to_example_spec() for e in examples]

    runner = make_step_runner(steps=_make_improvement_steps())
    call_count = 0

    def mock_check_termination(session, improvement_run_id, type_config):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return BlockingStatus(message="No definitions created yet.")
        return success_termination

    with patch("props.prompt_improve.reminder_handler.check_termination_condition", side_effect=mock_check_termination):
        result = await run_improvement_agent(
            examples=allowed_examples,
            baseline_definition_ids=[CRITIC_AGENT_DEFINITION_ID],
            token_budget=100_000,
            model="gpt-5-nano",
            docker_client=async_docker_client,
            db_config=synced_test_db,
            client=runner,
            critic_client=noop_openai_client,
            grader_client=noop_openai_client,
        )

    assert result.tokens_used >= 0

    with get_session() as session:
        session.query(AgentRun).filter_by(agent_run_id=result.run_id).one()


# =============================================================================
# CLI Helper Integration Tests
# =============================================================================


def _make_leaderboard_check_steps() -> list[Step]:
    """Create step sequence that runs leaderboard and terminates.

    test_train_example_with_runs creates:
    - First run: found_credit=0.8 (80%)
    - Second run: found_credit=0.72 (80% * 0.9 = 72%)
    Average: ~76%

    We verify multiple indicators of health:
    - Contains "76%" (the computed average recall)
    - Contains "Recall" (table header showing metrics present)
    - Contains "critic" (definition ID present)
    - Contains "Runs" (column header showing run count present)
    """
    return [
        # 1. Run leaderboard command
        DockerExecCall(cmd=["critic-dev", "leaderboard", "--limit", "5"], timeout_ms=30000),
        # 2. Check multiple indicators of health using hamcrest matchers
        AssertDockerExecThenFinish(
            expected_output="",  # Not used when stdout_matchers provided
            stdout_matchers=[
                contains_string("76%"),  # Average recall value
                contains_string("Recall"),  # Table header
                contains_string("critic"),  # Definition ID
                contains_string("Runs"),  # Run count column
            ],
            message="Leaderboard test completed successfully.",
        ),
    ]


def _make_hard_examples_check_steps() -> list[Step]:
    """Create step sequence that runs hard-examples and terminates.

    test_train_example_with_runs creates runs with ~76% average recall.

    We verify multiple indicators of health:
    - Contains "76%" (the computed average recall)
    - Contains "test-fixtures" (snapshot slug present - shows all examples)
    - Contains "Recall" (table header showing metrics present)
    """
    return [
        DockerExecCall(cmd=["critic-dev", "hard-examples", "--limit", "5"], timeout_ms=30000),
        # Multiple indicators of health
        AssertDockerExecThenFinish(
            expected_output="",  # Not used when stdout_matchers provided
            stdout_matchers=[
                contains_string("76%"),  # Average recall value
                contains_string("test-fixtures"),  # Snapshot slug (shows all examples)
                contains_string("Recall"),  # Table header
            ],
            message="Hard examples test completed successfully.",
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_cli_leaderboard_in_improvement_agent(run_improvement_agent_with_steps, test_train_example_with_runs):
    """Test that leaderboard CLI command works from improvement agent container.

    Verifies:
    - leaderboard command runs successfully with RLS-scoped credentials
    - Output contains recall data from pre-populated grading decisions
    - Recall values reflect test data (first run: 80%, second run: 72%, avg ~76%)
    """
    result = await run_improvement_agent_with_steps(_make_leaderboard_check_steps())
    assert result.tokens_used >= 0


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_cli_hard_examples_in_improvement_agent(run_improvement_agent_with_steps, test_train_example_with_runs):
    """Test that hard-examples CLI command works from improvement agent container.

    Verifies:
    - hard-examples command runs successfully with RLS-scoped credentials
    - Output contains example data with actual recall values
    - Recall values reflect test data (~76% average)
    """
    result = await run_improvement_agent_with_steps(_make_hard_examples_check_steps())
    assert result.tokens_used >= 0
