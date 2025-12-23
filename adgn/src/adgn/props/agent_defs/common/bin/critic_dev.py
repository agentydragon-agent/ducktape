#!/usr/bin/env python3
"""Critic development CLI for optimizer and improvement agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Annotated, Any
from uuid import UUID

from rich.console import Console
from sqlalchemy import text
import typer

from adgn.cli_utils import async_run
from adgn.props.agent_defs.prompt_optimizer.examples.rollout_analysis import (
    show_execution_traces,
    show_grading_summary,
    show_run_status,
)
from adgn.props.agent_helpers import get_current_agent_run, get_current_agent_run_id
from adgn.props.agent_types import AgentType
from adgn.props.cli.cmd_stats import cmd_stats_critic_leaderboard, cmd_stats_example, fmt_float, fmt_model, fmt_pct
from adgn.props.db import get_session
from adgn.props.db.agent_definition_ids import CRITIC_AGENT_DEFINITION_ID
from adgn.props.db.models import AgentDefinition
from adgn.props.definition_utils import unpack_definition
from adgn.props.display import ColumnDef, build_table_from_schema
from adgn.props.splits import Split

# Add workspace to path for local imports (helpers.py is deployed to /workspace/)
sys.path.insert(0, "/workspace")

from helpers import create_critic_definition, report_failure, run_critic, run_grader  # type: ignore[import-not-found]

HELP_TEXT = """Critic development commands for iterating on agent definitions.

Common workflows:

  Start from base critic, edit, and submit:
    /workspace/bin/critic_dev.py fetch-base-critic /workspace/my_critic/
    # Edit /workspace/my_critic/AGENT.md
    /workspace/bin/critic_dev.py create-definition /workspace/my_critic/

  Run evaluation pipeline:
    /workspace/bin/critic_dev.py run-critic "my-def-id" "snapshot-slug" "scope-hash"
    /workspace/bin/critic_dev.py run-grader "critic-run-uuid"

  Analyze runs spawned by this agent:
    /workspace/bin/critic_dev.py run-status
    /workspace/bin/critic_dev.py traces --limit 10
    /workspace/bin/critic_dev.py grading-summary "critic-or-grader-run-uuid"

  View metrics (definitions and examples):
    /workspace/bin/critic_dev.py leaderboard
    /workspace/bin/critic_dev.py hard-examples --limit 10

  Report failure and abort:
    /workspace/bin/critic_dev.py report-failure "Error message"
"""

app = typer.Typer(name="critic-dev", help=HELP_TEXT, add_completion=False)


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


# ============================================================================
# Rollout Analysis Commands
# ============================================================================


@app.command("run-status")
def run_status_cmd() -> None:
    """Show run status statistics for critic and grader runs spawned by this agent.

    Displays counts of runs by status (completed, max_turns_exceeded, etc.)
    and identifies definitions with high failure rates.

    Examples:
        /workspace/bin/critic_dev.py run-status
    """
    with get_session() as session:
        parent_id = get_current_agent_run_id(session)
    show_run_status(parent_agent_run_id=parent_id)


@app.command("traces")
def traces_cmd(limit: Annotated[int, typer.Option("--limit", "-n", help="Number of recent runs to show")] = 5) -> None:
    """Show execution traces for recent critic runs spawned by this agent.

    Lists recent critic runs with tool counts and shows the full trace
    for the most recent run. Useful for understanding agent behavior patterns.

    Examples:
        /workspace/bin/critic_dev.py traces
        /workspace/bin/critic_dev.py traces --limit 10
    """
    with get_session() as session:
        parent_id = get_current_agent_run_id(session)
    show_execution_traces(limit=limit, parent_agent_run_id=parent_id)


@app.command("grading-summary")
def grading_summary_cmd(run_id: Annotated[str, typer.Argument(help="UUID of a critic or grader run")]) -> None:
    """Show grading decision summary for a critic or grader run.

    Accepts either a critic run ID (finds associated grader) or grader run ID directly.
    Displays credit breakdown, TP/occurrence counts, and missed issues.

    Example:
        /workspace/bin/critic_dev.py grading-summary "12345678-1234-1234-1234-123456789abc"
    """
    show_grading_summary(agent_run_id=UUID(run_id))


# ============================================================================
# Metrics Commands
# ============================================================================


@app.command("leaderboard")
def leaderboard_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Number of definitions to show")] = 20,
) -> None:
    """Show top definitions by recall on accessible data.

    For prompt_optimizer: Shows TRAIN split metrics (VALID requires SECURITY DEFINER function).
    For improvement: Shows metrics for allowed_examples (any split).

    Example:
        /workspace/bin/critic_dev.py leaderboard --limit 10
    """
    # Prompt optimizer queries TRAIN explicitly; improvement lets RLS filter to allowed_examples
    with get_session() as session:
        agent_run = get_current_agent_run(session)
        split_filter = Split.TRAIN if agent_run.type_config.agent_type == AgentType.PROMPT_OPTIMIZER else None
    cmd_stats_critic_leaderboard(split=split_filter, example_kind=None, top=limit, bottom=None)


@app.command("hard-examples")
def hard_examples_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Number of examples to show")] = 20,
) -> None:
    """Show examples with lowest recall (hardest to solve) on accessible data.

    For prompt_optimizer: Shows TRAIN split examples.
    For improvement: Shows allowed_examples (any split).

    Example:
        /workspace/bin/critic_dev.py hard-examples --limit 10
    """
    # Prompt optimizer queries TRAIN explicitly; improvement lets RLS filter to allowed_examples
    with get_session() as session:
        agent_run = get_current_agent_run(session)
        split_filter = Split.TRAIN if agent_run.type_config.agent_type == AgentType.PROMPT_OPTIMIZER else None
    cmd_stats_example(split=split_filter, top=None, bottom=limit)


@app.command("valid-leaderboard")
def valid_leaderboard_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Number of definitions to show")] = 20,
) -> None:
    """Show top definitions by recall on validation split (whole-snapshot only).

    Uses SECURITY DEFINER function to access black-box validation metrics.
    Shows occurrence-weighted recall (total_credit / n_occurrences).

    Example:
        /workspace/bin/critic_dev.py valid-leaderboard --limit 10
    """
    console = Console()

    @dataclass
    class ValidationLeaderboardRow:
        """Row from validation leaderboard query."""

        critic_definition_id: str
        critic_model: str
        n_runs: int
        sum_credit: float | None
        sum_occurrences: int | None
        mean_recall: float | None
        stddev_recall: float | None

    with get_session() as session:
        # Query validation aggregates via SECURITY DEFINER function
        # Include total_credit and n_occurrences for occurrence-weighted context
        raw_results = session.execute(
            text("""
                SELECT
                    critic_definition_id,
                    critic_model,
                    COUNT(*) as n_runs,
                    SUM(total_credit) as sum_credit,
                    SUM(n_occurrences) as sum_occurrences,
                    AVG(total_credit / NULLIF(n_occurrences, 0)) as mean_recall,
                    STDDEV_SAMP(total_credit / NULLIF(n_occurrences, 0)) as stddev_recall
                FROM get_validation_full_snapshot_aggregates()
                GROUP BY critic_definition_id, critic_model
                ORDER BY mean_recall DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

        if not raw_results:
            console.print("[yellow]No validation results found.[/yellow]")
            return

        # Convert to typed rows
        results = [
            ValidationLeaderboardRow(
                critic_definition_id=row[0] or "",
                critic_model=row[1] or "",
                n_runs=row[2] or 0,
                sum_credit=row[3],
                sum_occurrences=int(row[4]) if row[4] is not None else None,
                mean_recall=row[5],
                stddev_recall=row[6],
            )
            for row in raw_results
        ]

        columns: list[ColumnDef[ValidationLeaderboardRow, Any]] = [
            ColumnDef("Definition", lambda r: r.critic_definition_id[:20], width=20),
            ColumnDef("Model", lambda r: r.critic_model, fmt_model, width=12),
            ColumnDef("Runs", lambda r: r.n_runs, str, justify="right", width=5),
            ColumnDef("Credit", lambda r: r.sum_credit, lambda v: fmt_float(v, decimals=1), justify="right", width=7),
            ColumnDef(
                "Occs",
                lambda r: r.sum_occurrences,
                lambda v: str(v) if v is not None else "—",
                justify="right",
                width=6,
            ),
            ColumnDef("Recall", lambda r: r.mean_recall, fmt_pct, justify="right", width=7),
            ColumnDef("σ", lambda r: r.stddev_recall, lambda v: fmt_float(v, decimals=3), justify="right", width=6),
        ]

        console.print(f"\n[bold]Top {limit} Definitions by Validation Recall (Occurrence-Weighted)[/bold]\n")
        table = build_table_from_schema(results, columns)
        console.print(table)


if __name__ == "__main__":
    app()
