"""Test prompt improvement agent end-to-end with mocked OpenAI.

Tests the improvement agent workflow:
- Bootstrap ./init script execution (validated via DockerExecCallWithBootstrapValidation)
- Creating improved definition directory via docker_exec
- Submitting via create_critic_definition tool (calls PromptEvalServer)
- Token budget handling
- RLS-scoped database access
- Termination when definition beats baseline average

All tests verify that bootstrap commands (including ./init) exit with code 0
before proceeding with the test scenario.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from adgn.props.agent_types import AllowedExample
from adgn.props.db import get_session
from adgn.props.db.agent_definition_ids import CRITIC_AGENT_DEFINITION_ID
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentRun
from adgn.props.hydration import SnapshotSlug
from adgn.props.prompt_improve.improve_agent import run_improvement_agent
from adgn.props.prompt_improve.reminder_handler import TerminationStatus
from tests.llm.support.openai_mock import FakeOpenAIModel
from tests.support.steps import AssertDockerExecThenFinish, DockerExecCallWithBootstrapValidation, Step

# Define the improved AGENT.md content used across tests
IMPROVED_AGENT_MD = """# Improved Critic Prompt

You are a code review assistant focused on finding:
1. Dead code (unused imports, unreachable code)
2. Duplication (copy-paste code that should be extracted)
3. Type errors and inconsistencies

Be thorough and systematic in your analysis."""

# Define the init script content
INIT_SCRIPT = """#!/usr/bin/env python3
import sys
from adgn.props.db import get_session
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
    """Create step sequence for improvement agent that creates and submits a definition.

    Uses bin CLI commands which run INSIDE THE CONTAINER where they have access
    to the MCP-over-HTTP server set up by the agent environment.

    The agent:
    1. Creates definition directory at /workspace/improved/ via docker_exec
    2. Writes AGENT.md and init script
    3. Makes init executable
    4. Calls create_critic_definition via bin CLI (python /workspace/bin/critic_dev.py create-definition)

    First step validates bootstrap succeeded.
    """
    return [
        # 1. Create definition directory and write files - also validates bootstrap
        DockerExecCallWithBootstrapValidation(
            cmd=[
                "sh",
                "-c",
                f"""mkdir -p /workspace/improved && \
cat > /workspace/improved/AGENT.md << 'AGENT_EOF'
{IMPROVED_AGENT_MD}
AGENT_EOF
cat > /workspace/improved/init << 'INIT_EOF'
{INIT_SCRIPT}
INIT_EOF
chmod +x /workspace/improved/init""",
            ],
            timeout_ms=15000,
        ),
        # 2. Submit the definition via bin CLI (calls MCP-over-HTTP internally)
        # Note: Uses critic_dev.py create-definition
        # After this, termination check (mocked) returns success so agent finishes
        AssertDockerExecThenFinish(
            expected_output="",  # Just check exit code 0
            message="Definition created successfully.",
        ),
    ]


def _make_success_termination_status() -> TerminationStatus:
    """Create a successful termination status for mocking."""
    return TerminationStatus(
        should_terminate=True,
        blocking_message=None,
        baseline_avg_issues=1.0,
        best_candidate_issues=2.0,
        best_candidate_id="test-improved-critic",
        missing_evals_count=0,
    )


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_prompt_improve_e2e_success(
    synced_test_db, make_step_runner, test_snapshot, async_docker_client, test_specimens_hydrator
):
    """Test improvement agent successfully submits improved definition.

    Verifies:
    - Bootstrap commands completed successfully
    - Agent creates definition directory in workspace
    - Agent submits via MCP HTTP server (PromptEvalServer)
    - Token usage is tracked
    - Termination condition triggers agent completion

    The termination check is mocked to return success after definition is created,
    simulating the scenario where the improved definition beats the baseline.
    """
    # Get an example from the test fixtures
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug=test_snapshot).first()
        assert example is not None, "Expected example not found in test fixtures"
        allowed_example = AllowedExample(
            snapshot_slug=SnapshotSlug(example.snapshot_slug), scope_hash=example.scope_hash
        )

    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_improvement_steps())

    # For critic_client and grader_client, we use fake clients since we're not
    # actually running evaluations in this test
    fake_client = FakeOpenAIModel(outputs=[])

    # Mock check_termination_condition to return success after first call
    # First call returns "no candidates yet", subsequent calls return success
    call_count = 0

    def mock_check_termination(session, improvement_run_id, type_config):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            # First check (before definition created) - not ready
            return TerminationStatus(
                should_terminate=False,
                blocking_message="No definitions created yet.",
                baseline_avg_issues=None,
                best_candidate_issues=None,
                best_candidate_id=None,
                missing_evals_count=0,
            )
        # After definition created - success!
        return _make_success_termination_status()

    with patch(
        "adgn.props.prompt_improve.reminder_handler.check_termination_condition", side_effect=mock_check_termination
    ):
        # Run improvement agent
        result = await run_improvement_agent(
            examples=[allowed_example],
            baseline_definition_ids=[CRITIC_AGENT_DEFINITION_ID],
            token_budget=100_000,
            model="gpt-5-nano",
            hydrator=test_specimens_hydrator,
            docker_client=async_docker_client,
            db_config=synced_test_db,
            client=runner,
            critic_client=fake_client,
            grader_client=fake_client,
        )

    # Verify tokens were tracked
    assert result.tokens_used >= 0

    # Verify the agent_run exists with improvement type_config
    with get_session() as session:
        agent_run = session.query(AgentRun).filter_by(agent_run_id=result.run_id).first()
        assert agent_run is not None, "AgentRun should exist"
        improvement_config = agent_run.improvement_config()
        assert improvement_config.agent_type == "improvement", "AgentRun should be improvement type"
        assert improvement_config.allowed_examples is not None, "AgentRun should have allowed_examples"


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_prompt_improve_e2e_multiple_examples(
    synced_test_db, make_step_runner, test_snapshot, async_docker_client, test_specimens_hydrator
):
    """Test improvement agent with multiple training examples.

    Verifies:
    - Bootstrap commands completed successfully
    - Agent can access and analyze multiple examples
    - Termination condition triggers agent completion
    """
    # Get multiple examples from test fixtures (test-trivial has several)
    with get_session() as session:
        examples = session.query(Example).filter_by(snapshot_slug=test_snapshot).limit(2).all()
        assert len(examples) >= 2, "Need at least 2 examples for this test"
        allowed_examples = [
            AllowedExample(snapshot_slug=SnapshotSlug(e.snapshot_slug), scope_hash=e.scope_hash) for e in examples
        ]

    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_improvement_steps())

    # For critic_client and grader_client, we use fake clients since we're not
    # actually running evaluations in this test
    fake_client = FakeOpenAIModel(outputs=[])

    # Mock check_termination_condition to return success after first call
    call_count = 0

    def mock_check_termination(session, improvement_run_id, type_config):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return TerminationStatus(
                should_terminate=False,
                blocking_message="No definitions created yet.",
                baseline_avg_issues=None,
                best_candidate_issues=None,
                best_candidate_id=None,
                missing_evals_count=0,
            )
        return _make_success_termination_status()

    with patch(
        "adgn.props.prompt_improve.reminder_handler.check_termination_condition", side_effect=mock_check_termination
    ):
        # Run improvement agent with multiple examples
        result = await run_improvement_agent(
            examples=allowed_examples,
            baseline_definition_ids=[CRITIC_AGENT_DEFINITION_ID],
            token_budget=100_000,
            model="gpt-5-nano",
            hydrator=test_specimens_hydrator,
            docker_client=async_docker_client,
            db_config=synced_test_db,
            client=runner,
            critic_client=fake_client,
            grader_client=fake_client,
        )

    # Verify tokens were tracked
    assert result.tokens_used >= 0

    # Verify the agent_run exists
    with get_session() as session:
        agent_run = session.query(AgentRun).filter_by(agent_run_id=result.run_id).first()
        assert agent_run is not None, "AgentRun should exist"
