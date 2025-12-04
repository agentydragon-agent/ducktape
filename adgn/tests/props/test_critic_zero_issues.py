"""Test critic agent successfully submits zero issues on clean trivial code.

Verifies the fix for the infinite loop bug where agents tried to send text responses
instead of calling submit(issues=0) when finding no violations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adgn.mcp.exec.models import ExecInput
from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Critique, Snapshot
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.models.snapshot import LocalSource
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

# Simple max-recall system prompt that shouldn't find issues in trivial clean code
SIMPLE_MAX_RECALL_PROMPT = """# Clean Code Critic

Find code quality issues, design smells, and violations of best practices.

## What to Flag
- Unused imports, variables, functions
- Type annotation issues (missing, incorrect, inconsistent)
- Error handling problems (bare except, swallowed exceptions)
- Code duplication
- Overly complex functions
- Missing docstrings for public functions
- Security issues (hardcoded secrets, SQL injection risks)

## Method
1. Read files as needed
2. Look for violations
3. Report each issue via critic_submit tools
4. Call submit(issues=N) when done (N=0 if no issues found)

Focus on concrete, actionable findings with specific line numbers.
"""


# Note: Using test_trivial_specimen fixture from conftest.py
# which loads from tests/props/fixtures/specimens/test-trivial/


@pytest.fixture
def critic_test_db_setup(test_trivial_specimen, test_db):
    """Set up database records for critic testing: Snapshot + prompt.

    Returns:
        tuple[str, str]: (snapshot_slug, prompt_sha256)
    """
    slug = test_trivial_specimen.slug

    # Insert snapshot into database
    with get_session() as session:
        spec_record = Snapshot(slug=slug, split="test", source=LocalSource(vcs="local", root="."))
        session.add(spec_record)
        session.commit()

    # Upsert prompt using proper helper
    prompt_sha256 = hash_and_upsert_prompt(SIMPLE_MAX_RECALL_PROMPT)

    return slug, prompt_sha256


def _make_critic_response_sequence() -> list:
    """Create response sequence for critic that finds zero issues and calls submit(issues_count=0)."""
    factory = ResponsesFactory("gpt-5-nano")

    return [
        # 1. Read the Python file
        factory.make_mcp_tool_call(
            "docker", "docker_exec", ExecInput(cmd=["cat", "/workspace/subtract.py"], timeout_ms=5000)
        ),
        # 2. Call submit with zero issues
        factory.make(factory.tool_call("critic_submit_submit", {"issues_count": 0})),
    ]


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_zero_issues_submits_successfully(
    test_trivial_specimen, make_openai_client, production_specimens_registry, critic_test_db_setup
):
    """Test that critic successfully calls submit(issues=0) when finding no issues.

    This is a regression test for the infinite loop bug where RequireAnyTool()
    forced the agent to call dummy tools instead of completing with submit(issues=0).
    """
    slug, prompt_sha256 = critic_test_db_setup
    specimen_dir = test_trivial_specimen.content_root

    # Create fake OpenAI client with expected tool call sequence
    client = make_openai_client(_make_critic_response_sequence())

    # Run critic
    input_data = CriticInput(snapshot_slug=slug, files={Path("subtract.py")}, prompt_sha256=prompt_sha256)

    # This should complete successfully without infinite loop
    output, critic_run_id, critique_id = await run_critic(
        input_data=input_data,
        client=client,
        content_root=specimen_dir,
        registry=production_specimens_registry,
        mount_properties=False,
    )

    # Verify output
    assert output.result is not None
    assert len(output.result.issues) == 0, "Should find zero issues in trivial clean code"
    assert critic_run_id is not None
    assert critique_id is not None

    # Verify database records
    with get_session() as session:
        run = session.get(CriticRun, critic_run_id)
        assert run is not None
        assert run.snapshot_slug == slug
        assert run.critique_id == critique_id

        critique = session.get(Critique, critique_id)
        assert critique is not None
        payload = critique.payload
        assert payload["issues"] == []
        assert len(payload["issues"]) == 0


@pytest.mark.requires_docker
@pytest.mark.requires_postgres
async def test_critic_does_not_infinite_loop_on_zero_issues(
    test_trivial_specimen, make_openai_client, production_specimens_registry, critic_test_db_setup
):
    """Verify critic doesn't get stuck in infinite loop when finding zero issues.

    Before the fix, RequireAnyTool() would force dummy docker_exec calls indefinitely.
    After the fix, the agent calls submit(issues=0) and the loop terminates via GateUntil.
    """
    slug, prompt_sha256 = critic_test_db_setup
    specimen_dir = test_trivial_specimen.content_root

    # Create response sequence with LIMITED docker_exec calls
    # If the bug exists, this will fail because agent keeps calling docker_exec
    factory = ResponsesFactory("gpt-5-nano")
    responses = [
        factory.make_mcp_tool_call("docker", "docker_exec", ExecInput(cmd=["ls", "/workspace"], timeout_ms=5000)),
        factory.make_mcp_tool_call(
            "docker", "docker_exec", ExecInput(cmd=["cat", "/workspace/subtract.py"], timeout_ms=5000)
        ),
        # After reading file, should call submit(issues_count=0), NOT more docker_exec
        factory.make(factory.tool_call("critic_submit_submit", {"issues_count": 0})),
    ]

    client = make_openai_client(responses)

    input_data = CriticInput(snapshot_slug=slug, files={Path("subtract.py")}, prompt_sha256=prompt_sha256)

    # This should complete in 3 turns, not loop infinitely
    output, _, _ = await run_critic(
        input_data=input_data,
        client=client,
        content_root=specimen_dir,
        registry=production_specimens_registry,
        mount_properties=False,
    )

    assert output.result is not None
    assert len(output.result.issues) == 0

    # Verify we used exactly the expected number of responses (no infinite loop)
    # The fake client will raise if more responses are requested
    assert client.calls <= len(responses), f"Agent made {client.calls} calls, expected <= {len(responses)}"
