"""Test prompt improvement agent end-to-end with mocked OpenAI.

Tests the improvement agent workflow:
- Writing improved prompt to workspace via docker_exec
- Submitting via CLI helper (which calls MCP-over-HTTP server)
- Token budget handling
- RLS-scoped database access
- Prompt provenance tracking (improvement_run_id FK)
"""

from __future__ import annotations

import hashlib

import pytest

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import ImprovementRun, Prompt
from adgn.props.hydration import SnapshotSlug
from adgn.props.prompt_improve.improve_agent import OutcomeSuccess, run_improvement_agent
from tests.support.steps import AssertDockerExecThenCall, DockerExecCallWithBootstrapValidation, Step

# Define the improved prompt content used across tests
IMPROVED_PROMPT_CONTENT = """# Improved Critic Prompt

You are a code review assistant focused on finding:
1. Dead code (unused imports, unreachable code)
2. Duplication (copy-paste code that should be extracted)
3. Type errors and inconsistencies

Be thorough and systematic in your analysis."""


def _make_improvement_steps() -> list[Step]:
    """Create step sequence for improvement agent that writes and submits a prompt.

    Uses CLI helper commands which run INSIDE THE CONTAINER where they have access
    to the MCP-over-HTTP server set up by the agent environment.

    The agent:
    1. Writes improved prompt to /workspace/improved-prompt.md via docker_exec
    2. Calls submit_prompt via CLI helper (adgn-properties agent-helper improvement submit-prompt)

    First step validates bootstrap succeeded.
    """
    return [
        # 1. Write improved prompt to workspace via docker_exec - also validates bootstrap
        DockerExecCallWithBootstrapValidation(
            cmd=[
                "sh",
                "-c",
                f"cat > /workspace/improved-prompt.md << 'PROMPT_EOF'\n{IMPROVED_PROMPT_CONTENT}\nPROMPT_EOF",
            ],
            timeout_ms=15000,
        ),
        # 2. Submit the prompt via CLI helper (calls MCP-over-HTTP internally)
        AssertDockerExecThenCall(
            expected_output="",  # Just check exit code 0
            next_cmd=[
                "adgn-properties",
                "agent-helper",
                "improvement",
                "submit-prompt",
                "improved-prompt.md",
                "Added structured focus areas for dead code, duplication, and type errors",
                "Better detection of dead code and duplication patterns",
            ],
            timeout_ms=15000,
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_prompt_improve_e2e_success(
    synced_test_db, make_step_runner, test_snapshot, async_docker_client, test_specimens_hydrator
):
    """Test improvement agent successfully submits improved prompt.

    Verifies:
    - Bootstrap commands completed successfully
    - Agent writes prompt to workspace
    - Agent submits via MCP HTTP server
    - Outcome is success with submission details
    - Token usage is tracked
    - Prompt provenance tracking (improvement_run_id FK)
    """
    # Get an example from the test fixtures
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug=test_snapshot).first()
        assert example is not None, "Expected example not found in test fixtures"
        example_key = (SnapshotSlug(example.snapshot_slug), example.scope_hash)

    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_improvement_steps())

    # Run improvement agent
    result = await run_improvement_agent(
        examples=[example_key],
        current_prompt="You are a code reviewer.",
        token_budget=100_000,
        model="gpt-5-nano",
        hydrator=test_specimens_hydrator,
        docker_client=async_docker_client,
        db_config=synced_test_db,
        client=runner,
    )

    # Verify outcome
    assert isinstance(result.outcome, OutcomeSuccess), f"Expected success, got {result.outcome}"

    # Verify submission content
    submission = result.outcome.submission
    assert "Improved Critic Prompt" in submission.prompt_text
    assert "dead code" in submission.rationale.lower()
    assert "dead code" in submission.expected_improvement.lower()

    # Verify tokens were tracked
    assert result.tokens_used >= 0

    # Verify provenance tracking: improvement_run and prompt are linked
    with get_session() as session:
        # Check improvement_run was created
        improvement_run = session.query(ImprovementRun).filter_by(id=result.run_id).first()
        assert improvement_run is not None, "ImprovementRun should be created"
        assert improvement_run.allowed_examples is not None

        # Check prompt was upserted with improvement_run_id
        prompt_sha = hashlib.sha256(submission.prompt_text.encode()).hexdigest()
        prompt = session.query(Prompt).filter_by(prompt_sha256=prompt_sha).first()
        assert prompt is not None, "Prompt should be upserted"
        assert prompt.improvement_run_id == result.run_id, "Prompt should link to improvement run"


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_prompt_improve_e2e_multiple_examples(
    synced_test_db, make_step_runner, test_snapshot, async_docker_client, test_specimens_hydrator
):
    """Test improvement agent with multiple training examples.

    Verifies:
    - Bootstrap commands completed successfully
    - Agent can access and analyze multiple examples
    """
    # Get multiple examples from test fixtures (test-trivial has several)
    with get_session() as session:
        examples = session.query(Example).filter_by(snapshot_slug=test_snapshot).limit(2).all()
        assert len(examples) >= 2, "Need at least 2 examples for this test"
        example_keys: list[tuple[SnapshotSlug, str | None]] = [
            (SnapshotSlug(e.snapshot_slug), e.scope_hash) for e in examples
        ]

    # Create step runner with bootstrap validation - implements OpenAIModelProto directly
    runner = make_step_runner(steps=_make_improvement_steps())

    # Run improvement agent with multiple examples
    result = await run_improvement_agent(
        examples=example_keys,
        current_prompt="You are a code reviewer.",
        token_budget=100_000,
        model="gpt-5-nano",
        hydrator=test_specimens_hydrator,
        docker_client=async_docker_client,
        db_config=synced_test_db,
        client=runner,
    )

    # Verify success
    assert isinstance(result.outcome, OutcomeSuccess)
    assert result.outcome.submission.prompt_text is not None
