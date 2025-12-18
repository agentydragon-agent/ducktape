"""Prompt optimizer agent CLI helper commands.

Provides CLI access to optimizer helper functions for debugging and manual testing.

Usage:
    adgn-properties agent-helper optimizer upsert-prompt /workspace/critic_v1.txt
    adgn-properties agent-helper optimizer run-critic "test-fixtures/test-trivial" "abc123..." "def456..." --max-turns 15
    adgn-properties agent-helper optimizer run-grader "12345678-1234-..." --max-turns 200
    adgn-properties agent-helper optimizer report-failure "Budget exceeded"
"""

from __future__ import annotations

import typer

from adgn.cli_utils import async_run
from adgn.props.prompt_optimize.helpers import report_failure, run_critic, run_grader, upsert_prompt

app = typer.Typer(help="Prompt optimizer agent helper commands")


@app.command("upsert-prompt")
@async_run
async def optimizer_upsert_prompt(file_path: str = typer.Argument(..., help="Absolute path to prompt file")) -> None:
    """Upsert a prompt from a file and return its SHA256 hash.

    Example:
        adgn-properties agent-helper optimizer upsert-prompt /workspace/critic_v1.txt
    """
    output = await upsert_prompt(file_path=file_path)
    typer.echo(f"Upserted prompt: {output.prompt_sha256}")


@app.command("run-critic")
@async_run
async def optimizer_run_critic(
    snapshot_slug: str = typer.Argument(..., help="Snapshot identifier"),
    scope_hash: str = typer.Argument(..., help="Scope hash (files to review)"),
    prompt_sha256: str = typer.Argument(..., help="SHA256 hash of the prompt"),
    max_turns: int = typer.Option(10, "--max-turns", "-t", help="Max agent turns"),
) -> None:
    """Run critic on an example and return the critic run ID.

    Example:
        adgn-properties agent-helper optimizer run-critic \\
            "test-fixtures/test-trivial" "abc123..." "def456..." --max-turns 15
    """
    output = await run_critic(
        snapshot_slug=snapshot_slug, scope_hash=scope_hash, prompt_sha256=prompt_sha256, max_turns=max_turns
    )
    typer.echo(f"Critic run ID: {output.critic_run_id}")


@app.command("run-grader")
@async_run
async def optimizer_run_grader(
    critic_run_id: str = typer.Argument(..., help="UUID of the critic run to grade"),
    max_turns: int = typer.Option(200, "--max-turns", "-t", help="Max agent turns"),
) -> None:
    """Run grader on a critique and return the grader run ID.

    Example:
        adgn-properties agent-helper optimizer run-grader "12345678-1234-..." --max-turns 200
    """
    output = await run_grader(critic_run_id=critic_run_id, max_turns=max_turns)
    typer.echo(f"Grader run ID: {output.grader_run_id}")
    typer.echo(f"Message: {output.message}")


@app.command("report-failure")
@async_run
async def optimizer_report_failure(
    message: str = typer.Argument(..., help="Error message explaining why optimization could not be completed"),
) -> None:
    """Report that optimization could not be completed and abort.

    Use this when the optimization run should be aborted (e.g., critical errors,
    no viable path forward, or test completion).

    Example:
        adgn-properties agent-helper optimizer report-failure "Budget exceeded"
    """
    result = await report_failure(message=message)
    typer.echo(result)
