#!/usr/bin/env python3
"""Critic development CLI for optimizer and improvement agents.

Both prompt optimizer and improvement agents use this CLI for iterating
on critic agent definitions. Commands for:

- Fetching and unpacking the base critic definition
- Creating critic definitions from directories
- Running critics on examples
- Running graders on critiques
- Reporting agent failures

Run '/workspace/bin/critic_dev.py --help' for all commands.

Usage:
    /workspace/bin/critic_dev.py fetch-base-critic /workspace/my_critic/
    /workspace/bin/critic_dev.py create-definition /workspace/my_critic/
    /workspace/bin/critic_dev.py run-critic "definition-id" "snapshot-slug" "scope-hash"
    /workspace/bin/critic_dev.py run-grader "critic-run-uuid"
    /workspace/bin/critic_dev.py report-failure "Error message"
"""

from __future__ import annotations

import sys
from typing import Annotated

# Add workspace to path for local imports (helpers.py is deployed to /workspace/)
sys.path.insert(0, "/workspace")

from helpers import create_critic_definition, report_failure, run_critic, run_grader  # type: ignore[import-not-found]
import typer

from adgn.cli_utils import async_run

app = typer.Typer(
    name="critic-dev", help="Critic development commands for iterating on agent definitions.", add_completion=False
)


@app.command("fetch-base-critic")
def fetch_base_critic_cmd(
    output_dir: Annotated[
        str, typer.Argument(help="Directory to unpack the base critic definition into (will be created)")
    ],
) -> None:
    """Fetch and unpack the built-in base critic definition.

    Downloads the base critic definition from the database and unpacks it to the
    specified directory. Start from this to get sane defaults (init script, docs, etc.)
    then modify AGENT.md with your improvements.

    Examples:
        /workspace/bin/critic_dev.py fetch-base-critic /workspace/my_critic/
        /workspace/bin/critic_dev.py fetch-base-critic /workspace/improved_v2/
    """
    from pathlib import Path

    from adgn.props.db import get_session
    from adgn.props.db.agent_definition_ids import CRITIC_AGENT_DEFINITION_ID
    from adgn.props.db.models import AgentDefinition
    from adgn.props.definition_utils import unpack_definition

    output_path = Path(output_dir)
    if output_path.exists():
        typer.echo(f"Error: Directory already exists: {output_path}", err=True)
        raise typer.Exit(1)

    with get_session() as session:
        base_def = session.get(AgentDefinition, CRITIC_AGENT_DEFINITION_ID)
        if base_def is None:
            typer.echo(f"Error: Base critic definition not found: {CRITIC_AGENT_DEFINITION_ID}", err=True)
            raise typer.Exit(1)

        output_path.mkdir(parents=True)
        unpack_definition(base_def.archive, output_path)

    typer.echo(f"Unpacked base critic to: {output_path}")
    typer.echo(f"Edit {output_path}/AGENT.md with your improvements, then run:")
    typer.echo(f"  /workspace/bin/critic_dev.py create-definition {output_path}")


@app.command("create-definition")
@async_run
async def create_definition_cmd(
    definition_dir: Annotated[
        str, typer.Argument(help="Absolute path to definition directory (must contain AGENT.md and executable init)")
    ],
) -> None:
    """Create a critic definition from a directory.

    The directory must contain:
    - AGENT.md: System prompt for the critic
    - init: Executable bootstrap script (chmod +x)

    Returns the definition_id which can be used with run-critic.

    Examples:
        prompt-eval create-definition /workspace/my_critic/
        prompt-eval create-definition /workspace/improved_v2/
    """
    output = await create_critic_definition(definition_dir=definition_dir)
    typer.echo(f"Created definition: {output.definition_id}")


@app.command("run-critic")
@async_run
async def run_critic_cmd(
    definition_id: Annotated[
        str, typer.Argument(help="Agent definition ID (from create-definition, or 'critic' for baseline)")
    ],
    snapshot_slug: Annotated[str, typer.Argument(help="Snapshot identifier (e.g., 'test-fixtures/test-trivial')")],
    scope_hash: Annotated[str, typer.Argument(help="Scope hash identifying which files to review")],
    max_turns: Annotated[int, typer.Option("--max-turns", "-t", help="Maximum agent turns before timeout")] = 200,
) -> None:
    """Run critic on an example using an agent definition.

    Returns the critic_run_id which can be used with run-grader.

    Examples:
        prompt-eval run-critic critic "test-fixtures/test-trivial" "abc123..."
        prompt-eval run-critic my-custom-def "ducktape/2025-11-26-00" "def456..." --max-turns 100
    """
    output = await run_critic(
        definition_id=definition_id, snapshot_slug=snapshot_slug, scope_hash=scope_hash, max_turns=max_turns
    )
    typer.echo(f"Critic run ID: {output.critic_run_id}")


@app.command("run-grader")
@async_run
async def run_grader_cmd(
    critic_run_id: Annotated[str, typer.Argument(help="UUID of the critic run to grade")],
    max_turns: Annotated[int, typer.Option("--max-turns", "-t", help="Maximum agent turns before timeout")] = 200,
) -> None:
    """Grade a critique and compute recall metrics.

    Takes a critic_run_id and runs the grader to match reported issues
    against ground truth. Returns the grader_run_id.

    Examples:
        prompt-eval run-grader "12345678-1234-1234-1234-123456789abc"
        prompt-eval run-grader "12345678-..." --max-turns 100
    """
    output = await run_grader(critic_run_id=critic_run_id, max_turns=max_turns)
    typer.echo(f"Grader run ID: {output.grader_run_id}")
    typer.echo(f"Message: {output.message}")


@app.command("report-failure")
@async_run
async def report_failure_cmd(
    message: Annotated[str, typer.Argument(help="Error message explaining why the agent could not complete")],
) -> None:
    """Report that the agent could not complete and should abort.

    Use this when the optimization or improvement run should be aborted
    (e.g., critical errors, no viable path forward, budget exceeded).

    Examples:
        prompt-eval report-failure "Budget exceeded after 50 evaluations"
        prompt-eval report-failure "No examples available for this split"
    """
    result = await report_failure(message=message)
    typer.echo(result)


if __name__ == "__main__":
    app()
