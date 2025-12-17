"""Test critic agent successfully submits zero issues on clean trivial code.

Verifies the fix for the infinite loop bug where agents tried to send text responses
instead of calling submit(issues=0) when finding no violations.
"""

from __future__ import annotations

import pytest

from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, CriticRunStatus
from tests.support.responses import ResponsesFactory

# Trivial clean Python code that should have zero issues
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
    """Create response sequence for critic that finds zero issues and calls submit(issues_count=0)."""
    factory = ResponsesFactory("gpt-5-nano")

    return [
        # 1. Read the Python file
        factory.make(factory.docker_exec(["cat", "/workspace/subtract.py"], timeout_ms=5000)),
        # 2. Call submit with zero issues
        factory.make(
            factory.tool_call("critic_submit_submit", {"issues_count": 0, "summary": "Reviewed code, no issues found"})
        ),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_zero_issues_submits_successfully(
    synced_test_fixtures,
    test_trivial_specimen,
    make_openai_client,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
):
    """Test that critic successfully calls submit(issues=0) when finding no issues.

    This is a regression test for the infinite loop bug where RequireAnyTool()
    forced the agent to call dummy tools instead of completing with submit(issues=0).
    """
    # Create fake OpenAI client with expected tool call sequence
    client = make_openai_client(_make_critic_response_sequence())

    # Run critic
    input_data = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    # This should complete successfully without infinite loop
    critic_run_id, status = await run_critic(
        input_data=input_data,
        client=client,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_fixtures,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        mount_properties=False,
        max_turns=100,
    )

    # Verify status
    assert status == CriticRunStatus.COMPLETED, "Critic should succeed"
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
    synced_test_fixtures,
    test_trivial_specimen,
    make_openai_client,
    test_snapshot,
    test_prompt_sha,
    subtract_file_scope,
    async_docker_client,
    test_specimens_hydrator,
):
    """Verify critic doesn't get stuck in infinite loop when finding zero issues.

    Before the fix, RequireAnyTool() would force dummy docker_exec calls indefinitely.
    After the fix, the agent calls submit(issues=0) and the loop terminates via GateUntil.
    """
    # Create response sequence with LIMITED docker_exec calls
    # If the bug exists, this will fail because agent keeps calling docker_exec
    factory = ResponsesFactory("gpt-5-nano")
    responses = [
        factory.make(factory.docker_exec(["ls", "/workspace"], timeout_ms=5000)),
        factory.make(factory.docker_exec(["cat", "/workspace/subtract.py"], timeout_ms=5000)),
        # After reading file, should call submit(issues_count=0), NOT more docker_exec
        factory.make(
            factory.tool_call("critic_submit_submit", {"issues_count": 0, "summary": "Reviewed code, no issues found"})
        ),
    ]

    client = make_openai_client(responses)

    input_data = CriticInput(snapshot_slug=test_snapshot, scope=subtract_file_scope, prompt_sha256=test_prompt_sha)

    # This should complete in 3 turns, not loop infinitely
    _, status = await run_critic(
        input_data=input_data,
        client=client,
        hydrator=test_specimens_hydrator,
        db_config=synced_test_fixtures,
        prompt_optimization_run_id=None,
        docker_client=async_docker_client,
        mount_properties=False,
        max_turns=100,
    )

    assert status == CriticRunStatus.COMPLETED, "Critic should succeed"

    # Verify we used exactly the expected number of responses (no infinite loop)
    # The fake client will raise if more responses are requested
    assert client.calls <= len(responses), f"Agent made {client.calls} calls, expected <= {len(responses)}"
