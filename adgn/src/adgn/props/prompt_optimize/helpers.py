"""Prompt optimizer agent helpers for MCP tool calls.

These helpers wrap the prompt evaluation MCP server tools with Pydantic models
for type-safe input/output handling and clean error reporting.

Usage from within prompt optimizer agent:

    from adgn.props.prompt_optimize.helpers import upsert_prompt, run_critic, run_grader

    # Upsert a prompt from file (returns Pydantic model)
    output = await upsert_prompt("/workspace/my_prompt.txt")
    prompt_sha256 = output.prompt_sha256

    # Run critic on an example (returns Pydantic model)
    critic_output = await run_critic(
        snapshot_slug="test-fixtures/test-trivial",
        scope_hash=example.scope_hash,
        prompt_sha256=prompt_sha256,
        max_turns=15
    )

    # Grade the critique (returns Pydantic model)
    grader_output = await run_grader(str(critic_output.critic_run_id), max_turns=200)
    print(f"Grader run: {grader_output.grader_run_id}")
    print(grader_output.message)  # Instructions for querying metrics
"""

from __future__ import annotations

from uuid import UUID

from mcp.types import TextContent

from adgn.props.agent_helpers import mcp_client_from_env
from adgn.props.ids import SnapshotSlug
from adgn.props.prompt_optimize.prompt_optimizer import (
    ReportFailureInput,
    RunCriticOnExampleInput,
    RunCriticOutput,
    RunGraderInput,
    RunGraderOutput,
    UpsertPromptInput,
    UpsertPromptOutput,
)

# Note: fastmcp's call_tool() has raise_on_error=True by default.
# ToolError is raised automatically on failure, so no manual is_error checks needed.


async def upsert_prompt(file_path: str) -> UpsertPromptOutput:
    """Upsert a prompt from a file and return structured output.

    Args:
        file_path: Absolute path to prompt file (e.g., "/workspace/my_prompt.txt")

    Returns:
        UpsertPromptOutput with prompt_sha256 field

    Raises:
        RuntimeError: If the MCP call fails or returns an error

    Example:
        output = await upsert_prompt("/workspace/critic_v1.txt")
        print(f"Upserted prompt: {output.prompt_sha256}")
    """
    async with mcp_client_from_env() as (client, _):
        input_model = UpsertPromptInput(file_path=file_path)
        # raise_on_error=True (default) raises ToolError on failure
        result = await client.call_tool("upsert_prompt", input_model.model_dump(mode="json"))
        return UpsertPromptOutput.model_validate(result.structured_content)


async def run_critic(snapshot_slug: str, scope_hash: str, prompt_sha256: str, max_turns: int = 10) -> RunCriticOutput:
    """Run critic on an example and return structured output.

    Args:
        snapshot_slug: Snapshot identifier (e.g., "test-fixtures/test-trivial")
        scope_hash: Scope hash identifying which files to review
        prompt_sha256: SHA256 hash of the prompt to use
        max_turns: Maximum number of turns for the critic agent (default: 10)

    Returns:
        RunCriticOutput with critic_run_id field (UUID)

    Raises:
        ToolError: If the MCP call fails (raised automatically by fastmcp)

    Example:
        output = await run_critic(
            snapshot_slug="test-fixtures/test-trivial",
            scope_hash=example.scope_hash,
            prompt_sha256=prompt_sha,
            max_turns=15
        )
        print(f"Critic run: {output.critic_run_id}")
    """
    async with mcp_client_from_env() as (client, _):
        input_model = RunCriticOnExampleInput(
            snapshot_slug=SnapshotSlug(snapshot_slug),
            scope_hash=scope_hash,
            prompt_sha256=prompt_sha256,
            max_turns=max_turns,
        )
        result = await client.call_tool("run_critic_on_example", input_model.model_dump(mode="json"))
        return RunCriticOutput.model_validate(result.structured_content)


async def run_grader(critic_run_id: str, max_turns: int = 200) -> RunGraderOutput:
    """Run grader on a critique and return structured output.

    Args:
        critic_run_id: UUID of the critic run to grade
        max_turns: Maximum number of turns for the grader agent (default: 200, fixed in API)

    Returns:
        RunGraderOutput with grader_run_id and message fields

    Raises:
        ToolError: If the MCP call fails (raised automatically by fastmcp)

    Example:
        output = await run_grader(str(critic_run_id), max_turns=200)
        print(f"Grader run: {output.grader_run_id}")
        print(output.message)  # Instructions for querying metrics
    """
    async with mcp_client_from_env() as (client, _):
        input_model = RunGraderInput(
            critic_run_id=UUID(critic_run_id) if isinstance(critic_run_id, str) else critic_run_id, max_turns=max_turns
        )
        result = await client.call_tool("run_grader", input_model.model_dump(mode="json"))
        return RunGraderOutput.model_validate(result.structured_content)


async def report_failure(message: str) -> str:
    """Report that optimization could not be completed and abort.

    Use this when you determine the optimization run should be aborted
    (e.g., critical errors, no viable path forward, test completion).

    The agent loop will be stopped after this tool returns.

    Args:
        message: Error message explaining why optimization could not be completed

    Returns:
        Confirmation message from the server

    Raises:
        ToolError: If the MCP call fails (raised automatically by fastmcp)

    Example:
        result = await report_failure("Test completed successfully")
        print(result)  # "Optimization run marked as unsuccessful: ..."
    """
    async with mcp_client_from_env() as (client, _):
        input_model = ReportFailureInput(message=message)
        result = await client.call_tool("report_failure", input_model.model_dump(mode="json"))
        # report_failure returns text content
        for item in result.content:
            if isinstance(item, TextContent):
                return item.text
        raise RuntimeError("report_failure returned no text content")
