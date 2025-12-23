"""Prompt optimizer agent helpers for MCP tool calls.

These helpers wrap the prompt evaluation MCP server tools with Pydantic models
for type-safe input/output handling and clean error reporting.

Import from /workspace when running in an agent container:
    sys.path.insert(0, "/workspace")
    from helpers import create_critic_definition, run_critic, run_grader, report_failure

Usage:
    from adgn.props.models.examples import WholeSnapshotExample

    # Create a critic definition from a directory (returns Pydantic model)
    output = await create_critic_definition("/workspace/my_critic/")
    definition_id = output.definition_id

    # Run critic on an example using the definition (returns Pydantic model)
    critic_output = await run_critic(
        definition_id=definition_id,
        example=WholeSnapshotExample(snapshot_slug="test-fixtures/test-trivial"),
        max_turns=200
    )

    # Grade the critique (returns Pydantic model)
    grader_output = await run_grader(str(critic_output.critic_run_id), max_turns=200)
    print(f"Grader run: {grader_output.grader_run_id}")
"""

from __future__ import annotations

from uuid import UUID

from mcp.types import TextContent

from adgn.props.agent_helpers import mcp_client_from_env
from adgn.props.models.examples import ExampleSpec
from adgn.props.prompt_optimize.prompt_optimizer import (
    CreateCriticDefinitionInput,
    CreateCriticDefinitionOutput,
    ReportFailureInput,
    RunCriticInput,
    RunCriticOutput,
    RunGraderInput,
    RunGraderOutput,
)

# Note: fastmcp's call_tool() has raise_on_error=True by default.
# ToolError is raised automatically on failure, so no manual is_error checks needed.


async def create_critic_definition(definition_dir: str) -> CreateCriticDefinitionOutput:
    """Create a critic definition from a directory and return structured output.

    The directory must contain:
    - AGENT.md: System prompt for the critic
    - init: Executable bootstrap script

    Args:
        definition_dir: Absolute path to definition directory (e.g., "/workspace/critic-v1/")

    Returns:
        CreateCriticDefinitionOutput with definition_id field

    Raises:
        ToolError: If the MCP call fails or directory validation fails

    Example:
        output = await create_critic_definition("/workspace/critic_v1/")
        print(f"Created definition: {output.definition_id}")
    """
    async with mcp_client_from_env() as (client, _):
        input_model = CreateCriticDefinitionInput(definition_dir=definition_dir)
        # raise_on_error=True (default) raises ToolError on failure
        result = await client.call_tool("create_critic_definition", input_model.model_dump(mode="json"))
        return CreateCriticDefinitionOutput.model_validate(result.structured_content)


async def run_critic(definition_id: str, example: ExampleSpec, max_turns: int = 200) -> RunCriticOutput:
    """Run critic on an example using an agent definition.

    Args:
        definition_id: Agent definition ID (from create_critic_definition or 'critic' for baseline)
        example: ExampleSpec (WholeSnapshotExample or SingleTriggerSetExample)
        max_turns: Maximum number of turns for the critic agent (default: 200)

    Returns:
        RunCriticOutput with critic_run_id field (UUID)

    Raises:
        ToolError: If the MCP call fails (raised automatically by fastmcp)

    Example:
        from adgn.props.models.examples import WholeSnapshotExample

        output = await run_critic(
            definition_id="critic_abc123",
            example=WholeSnapshotExample(snapshot_slug="test-fixtures/test-trivial"),
            max_turns=200
        )
        print(f"Critic run: {output.critic_run_id}")
    """
    async with mcp_client_from_env() as (client, _):
        input_model = RunCriticInput(definition_id=definition_id, example=example, max_turns=max_turns)
        result = await client.call_tool("run_critic", input_model.model_dump(mode="json"))
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
