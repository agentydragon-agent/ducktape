"""Typer-based CLI entry for adgn-properties.

Incremental migration target: we will gradually move subcommands here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
import tempfile
from typing import Annotated
from uuid import UUID

import aiodocker
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.traceback import install as rich_traceback_install
from sqlalchemy import func
import typer
from typer_di import Depends, TyperDI

from adgn.cli.logging_callback import make_logging_callback
from adgn.cli_utils import async_run
from adgn.openai_utils.client_factory import build_client
from adgn.props.agent_types import AgentType, AllowedExample
from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.cli import common_options as opt
from adgn.props.cli.cmd_agent_definition import app as agent_definition_app
from adgn.props.cli.cmd_analyze_exec import cmd_analyze_exec
from adgn.props.cli.cmd_classify_noops import cmd_classify_noops
from adgn.props.cli.cmd_cluster_unknowns import app as cluster_unknowns_app
from adgn.props.cli.cmd_db import db_app
from adgn.props.cli.cmd_gepa import cmd_gepa
from adgn.props.cli.cmd_grade_validation import cmd_grade_validation
from adgn.props.cli.cmd_snapshot import snapshot_app
from adgn.props.cli.cmd_speak_with_dead import cmd_speak_with_dead
from adgn.props.cli.cmd_stats import stats_app
from adgn.props.cli.resources import get_hydrator
from adgn.props.cli.shared import BuildOptions, build_cmd, filter_files
from adgn.props.cluster_unknowns import cluster_unknowns
from adgn.props.critic.critic import run_critic
from adgn.props.critic.persistence import load_critic_submit_payload_mcp
from adgn.props.db import get_session, init_db
from adgn.props.db.config import get_database_config
from adgn.props.db.models import AgentRun, AgentRunStatus, GradingDecision, Snapshot
from adgn.props.db.query_builders import (
    DefinitionPerformanceRow,
    query_definition_performance_stats,
    query_recall_by_example,
)
from adgn.props.display import short_sha
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.eval_harness import run_all_evals
from adgn.props.grader.grader import grade_critic_run_by_id
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.lint_issue import run_specimen_lint_issue_async
from adgn.props.models.true_positive import LineRange, Occurrence
from adgn.props.prompt_improve.improve_agent import (
    OutcomeExhausted,
    OutcomeSuccess,
    OutcomeUnexpectedTermination,
    run_improvement_agent,
)
from adgn.props.prompt_optimize.prompt_optimizer import run_prompt_optimizer
from adgn.props.prompt_optimize.target_metric import TargetMetric
from adgn.props.prompts.builder import build_enforce_prompt
from adgn.props.prompts.schemas import build_input_schemas_json
from adgn.props.runs_context import RunsContext
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


def _get_critique_payload(critic_run_id: UUID | None):
    """Query critique payload from critic run (reconstructed from normalized tables).

    Returns MCP CriticSubmitPayload with issues loaded from normalized tables.
    """
    assert critic_run_id is not None, "Critic run ID must not be None"
    with get_session() as session:
        critic_run = session.get(AgentRun, critic_run_id)
        assert critic_run is not None, f"Critic run {critic_run_id} not found"
        assert critic_run.status == AgentRunStatus.COMPLETED, (
            f"Critic run {critic_run_id} did not complete successfully (status: {critic_run.status})"
        )
        # Load MCP payload from normalized tables
        return load_critic_submit_payload_mcp(session, critic_run_id, notes_md=critic_run.completion_summary)


app = TyperDI(help="adgn-properties — properties tooling", add_completion=False)

# Subcommand groups
app.add_typer(db_app, name="db")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(cluster_unknowns_app, name="cluster-unknowns")
app.add_typer(agent_definition_app, name="agent-definition")

# Configure logging via shared callback (default: WARNING level for props)
# Then add database initialization on top
_logging_callback = make_logging_callback(default_level="WARNING")


@app.callback()
def _init_logging_and_db(
    log_output: Annotated[
        str,
        typer.Option(
            "--log-output",
            envvar="ADGN_LOG_OUTPUT",
            help="Where to send logs: 'stderr' (default), 'stdout', 'none', or a file path",
        ),
    ] = "stderr",
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            envvar="ADGN_LOG_LEVEL",
            help="Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: WARNING)",
        ),
    ] = "WARNING",
) -> None:
    """Global callback to configure logging and initialize database for all subcommands."""
    # First, configure logging via the shared callback
    _logging_callback(log_output=log_output, log_level=log_level)

    # Suppress verbose OpenAI HTTP request/response logging (too noisy at DEBUG level)
    logging.getLogger("openai.http").setLevel(logging.WARNING)
    logging.getLogger("openai._base_client").setLevel(logging.WARNING)

    # Configure Rich traceback for CLI errors (increased detail for debugging)
    rich_traceback_install(show_locals=True, max_frames=50, extra_lines=2, width=120)

    # Initialize database once at CLI entry (uses production config from env vars)
    init_db()


@dataclass
class MetricsRow:
    iteration: int
    mean_recall: float
    tp: int
    fp: int
    fn: int
    unknown: int
    dir: str


def read_embedded_paths(paths: list[Path]) -> str:
    files_to_embed: list[Path] = []
    for q in paths:
        p = Path(q)
        if p.is_file():
            files_to_embed.append(p)
    return "\n\n".join(
        "\n".join([f'<file path=":/{p}">', p.read_text(encoding="utf-8"), "</file>"])
        for p in sorted(files_to_embed, key=str)
    )


@app.command("cluster-unknowns")
@async_run
async def cmd_cluster_unknowns(model: str = opt.OPT_MODEL, out_dir: Path | None = opt.OPT_OUTPUT_DIR) -> None:
    """Cluster all 'unknown' issues across all prompt_optimize runs via an in-proc MCP tool.

    The agent must submit a single payload of clusters: [{name: str, true_positives: [uid,...]}].
    """
    root = await cluster_unknowns(model=model, out_dir=out_dir, ctx=RunsContext.from_pkg_dir())
    typer.echo(f"Clusters written to: {root}/<snapshot>/clusters.json")


@app.command("prompt-optimize")
@async_run
async def prompt_optimize(
    target_metric: Annotated[
        TargetMetric,
        typer.Option(
            help="Terminal metric mode (REQUIRED): 'whole-repo' (black-box validation, only full-snapshot) or 'targeted' (allows per-file validation examples)"
        ),
    ],
    budget: float = typer.Option(50.0, "--budget", help="$ budget for optimization"),
    optimizer_model: str = opt.OPT_OPTIMIZER_MODEL,
    critic_model: str = opt.OPT_CRITIC_MODEL,
    grader_model: str = opt.OPT_GRADER_MODEL,
    verbose: bool = opt.OPT_VERBOSE,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt using prompt_eval MCP with $ budget."""
    docker_client = aiodocker.Docker()
    db_config = get_database_config()
    try:
        await run_prompt_optimizer(
            budget=budget,
            hydrator=hydrator,
            optimizer_client=build_client(optimizer_model),
            critic_client=build_client(critic_model),
            grader_client=build_client(grader_model),
            docker_client=docker_client,
            target_metric=target_metric,
            db_config=db_config,
            verbose=verbose,
        )
    finally:
        await docker_client.close()


@app.command("prompt-improve")
@async_run
async def prompt_improve_cmd(
    n_examples: int = typer.Option(10, "--n-examples", "-n", help="Number of training examples to analyze"),
    token_budget: int = typer.Option(200_000, "--token-budget", "-t", help="Maximum token budget"),
    model: str = opt.OPT_OPTIMIZER_MODEL,
    prompt_sha256: str | None = typer.Option(
        None, "--prompt-sha256", "-p", help="Prompt SHA256 to improve (default: best recent prompt)"
    ),
    out_dir: Path | None = typer.Option(None, "--out-dir", "-o", help="Output directory (default: temp dir in /tmp)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Run prompt improvement agent on training examples.

    Selects N Pareto-optimal training examples and runs improvement agent with
    token budget enforcement. The agent analyzes failure patterns and proposes
    an improved prompt.

    Example:
        adgn-properties prompt-improve
        adgn-properties prompt-improve -n 20 -t 100000 -p abc123def...
    """
    console = Console()
    console.print("\n[bold cyan]Prompt Improvement Agent[/bold cyan]\n")

    # Helper function for Pareto selection
    def select_pareto_examples(session, agent_definition_id_param: str, limit: int) -> list[AllowedExample]:
        """Select Pareto-optimal training examples for an agent definition."""
        # Query occurrence-weighted recall per example using helper
        results = query_recall_by_example(session, split=Split.TRAIN, agent_definition_id=agent_definition_id_param)

        if not results:
            raise ValueError(f"No grader runs found for definition {short_sha(agent_definition_id_param)}")

        # Build example scores dict
        example_scores: dict[AllowedExample, float] = {}
        for row in results:
            key = AllowedExample(snapshot_slug=row.snapshot_slug, scope_hash=row.scope_hash)
            example_scores[key] = row.recall

        # Sort by recall descending and take top N
        sorted_examples = sorted(example_scores.items(), key=lambda x: x[1], reverse=True)
        top_n = sorted_examples[:limit]
        logger.info(
            f"Selected {len(top_n)} Pareto-optimal examples (recall range: {top_n[-1][1]:.1%} to {top_n[0][1]:.1%})"
        )
        return [ex for ex, _score in top_n]

    # 1. Select agent definition to improve
    # NOTE: The --prompt-sha256 option is deprecated. This command now works on agent definitions.
    console.print("[dim]Loading agent definition from database...[/dim]")
    with get_session() as session:
        if prompt_sha256:
            # Legacy option - no longer supported
            console.print(
                "[red]Error:[/red] The --prompt-sha256 option is deprecated. "
                "The improvement command now operates on agent definitions."
            )
            console.print("[dim]This command needs redesign per Task 7 in docs/design/agent-definitions.md[/dim]")
            raise typer.Exit(1)
        # Auto-select: find prompts with enough training examples, pick best by validation LCB
        # Count training examples per prompt using two-phase approach for unified AgentRun model
        # Phase 1: Get all completed critic runs with grader runs on TRAIN split
        critic_runs = (
            session.query(AgentRun)
            .filter(
                AgentRun.type_config["agent_type"].astext == AgentType.CRITIC,
                AgentRun.status == AgentRunStatus.COMPLETED,
            )
            .all()
        )

        # Build index: agent_definition_id -> set of (snapshot_slug, scope_hash) for examples that have grader runs
        # NOTE: Originally indexed by prompt_sha256, but prompts were replaced by agent_definitions
        definition_to_examples: dict[str, set[tuple[str, str]]] = {}
        for cr in critic_runs:
            critic_config = cr.critic_config()
            snapshot_slug = critic_config.snapshot_slug
            scope_hash = critic_config.scope_hash
            definition_id = cr.agent_definition_id

            # Check if this snapshot is in TRAIN split
            snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).first()
            if not snapshot or snapshot.split != Split.TRAIN:
                continue

            # Check if there's a grader run for this critic run
            has_grader = (
                session.query(AgentRun)
                .filter(
                    AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
                    AgentRun.type_config["graded_agent_run_id"].astext == str(cr.agent_run_id),
                )
                .first()
            )
            if has_grader:
                if definition_id not in definition_to_examples:
                    definition_to_examples[definition_id] = set()
                definition_to_examples[definition_id].add((snapshot_slug, scope_hash))

        # Filter to definitions with enough examples
        definition_example_counts = [
            (def_id, len(examples))
            for def_id, examples in definition_to_examples.items()
            if len(examples) >= n_examples
        ]

        if not definition_example_counts:
            console.print(f"[red]Error:[/red] No definitions have {n_examples}+ training examples with grader runs")
            raise typer.Exit(1)

        eligible_definition_ids = {d for d, _ in definition_example_counts}

        # Get performance stats for eligible definitions
        stats = query_definition_performance_stats(session, limit=100)
        # Get validation stats for whole-snapshot examples
        valid_stats_key = (Split.VALID, "entire_snapshot")
        eligible_stats = [
            s
            for s in stats
            if s.agent_definition_id in eligible_definition_ids
            and valid_stats_key in s.stats
            and s.stats[valid_stats_key].success_count > 0
        ]

        if not eligible_stats:
            console.print(f"[red]Error:[/red] No prompts with {n_examples}+ training examples have validation results")
            raise typer.Exit(1)

        # Pick best by validation LCB (whole-snapshot)
        def get_lcb(s: DefinitionPerformanceRow) -> float:
            lcb = s.stats[valid_stats_key].lcb
            return lcb if lcb is not None else -1.0

        best = max(eligible_stats, key=get_lcb)
        definition_id = best.agent_definition_id

        example_count = next(count for d, count in definition_example_counts if d == definition_id)
        console.print(f"[green]✓[/green] Selected best definition: {definition_id} ({example_count} training examples)")

        # Display validation stats for all available scope kinds
        def format_lcb(lcb: float | None) -> str:
            return f"{lcb:.1%}" if lcb is not None else "N/A"

        for (split, scope_kind_str), split_stats in best.stats.items():
            if split == Split.VALID:
                console.print(
                    f"  Valid ({scope_kind_str}): recall={split_stats.mean_recall:.1%}, "
                    f"LCB={format_lcb(split_stats.lcb)}, "
                    f"n={split_stats.success_count}/{split_stats.total_count}, "
                    f"{split_stats.zero_count}z {split_stats.stuck_count}s {split_stats.context_count}c"
                )

    # 2. Select training examples
    console.print(f"\n[dim]Selecting {n_examples} training examples...[/dim]")
    with get_session() as session:
        allowed_examples = select_pareto_examples(session, definition_id, n_examples)
        if not allowed_examples:
            console.print("[red]Error:[/red] No training examples found")
            raise typer.Exit(1)

        if len(allowed_examples) < n_examples:
            console.print(
                f"[yellow]Warning:[/yellow] Only {len(allowed_examples)} examples available (requested {n_examples})"
            )

        console.print(f"[green]✓[/green] Selected {len(allowed_examples)} examples")

        table = Table(title="Training Examples")
        table.add_column("Snapshot", style="cyan")
        table.add_column("Scope Hash", style="dim")
        for ex in allowed_examples[:5]:
            table.add_row(str(ex.snapshot_slug), short_sha(ex.scope_hash))
        if len(allowed_examples) > 5:
            table.add_row("[dim]...[/dim]", f"[dim](+{len(allowed_examples) - 5} more)[/dim]")
        console.print(table)

    # 3. Run improvement agent
    console.print("\n[bold]Running improvement agent[/bold]")
    console.print(f"  Model: {model}")
    console.print(f"  Token budget: {token_budget:,}")
    console.print(f"  Examples: {len(allowed_examples)}")
    console.print()

    docker_client = aiodocker.Docker()
    db_config = get_database_config()
    openai_client = build_client(model)
    try:
        result = await run_improvement_agent(
            examples=allowed_examples,
            baseline_definition_ids=[definition_id],
            token_budget=token_budget,
            model=model,
            hydrator=hydrator,
            docker_client=docker_client,
            db_config=db_config,
            client=openai_client,
            critic_client=openai_client,
            grader_client=openai_client,
            output_dir=out_dir,
            verbose=verbose,
        )
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        if verbose:
            logger.exception("Improvement agent failed")
        raise typer.Exit(1)
    finally:
        await docker_client.close()

    # 5. Display results
    console.print()
    if isinstance(result.outcome, OutcomeSuccess):
        panel = Panel(
            f"[green]✓ Improvement agent completed successfully[/green]\n\n"
            f"[bold]Definition ID:[/bold] {result.outcome.definition_id}\n\n"
            f"[bold]Tokens:[/bold] {result.tokens_used:,} / {token_budget:,} "
            f"({100 * result.tokens_used / token_budget:.1f}%)\n\n"
            f"[bold]Issues found:[/bold] {result.outcome.issues_found:.1f}\n"
            f"[bold]Baseline avg:[/bold] {result.outcome.baseline_avg:.1f}",
            title="Improvement Result",
            border_style="green",
        )
        console.print(panel)
    elif isinstance(result.outcome, OutcomeExhausted):
        panel = Panel(
            f"[yellow]! Token budget exhausted[/yellow]\n\n"
            f"[bold]Tokens:[/bold] {result.tokens_used:,} / {token_budget:,} "
            f"({100 * result.tokens_used / token_budget:.1f}%)\n\n"
            f"The agent exhausted its token budget without submitting a prompt. "
            f"Try increasing --token-budget or reducing --n-examples.",
            title="Improvement Result",
            border_style="yellow",
        )
        console.print(panel)
    elif isinstance(result.outcome, OutcomeUnexpectedTermination):
        panel = Panel(
            f"[red]✗ Unexpected termination[/red]\n\n"
            f"[bold]Tokens:[/bold] {result.tokens_used:,} / {token_budget:,} "
            f"({100 * result.tokens_used / token_budget:.1f}%)\n\n"
            f"[bold]Message:[/bold] {result.outcome.message}",
            title="Improvement Result",
            border_style="red",
        )
        console.print(panel)

    console.print()


@app.command("snapshot-grade")
@async_run
async def snapshot_grade(
    critic_run_id: UUID = typer.Argument(..., help="Critic run ID (UUID) from database"),
    model: str = opt.OPT_MODEL,
    verbose: bool = opt.OPT_VERBOSE,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Grade a critic run by database ID against canonical findings.

    Fetches critic run from database, executes grader, and persists results.
    """
    docker_client = aiodocker.Docker()
    db_config = get_database_config()
    workspace_manager = WorkspaceManager.from_env()
    try:
        # Query database and grade critic run in single session
        with get_session() as session:
            grader_run_id = await grade_critic_run_by_id(
                session,
                critic_run_id,
                build_client(model),
                docker_client,
                hydrator,
                db_config,
                workspace_manager=workspace_manager,
                verbose=verbose,
                max_turns=200,
            )
            grader_run = session.get(AgentRun, grader_run_id)
            if grader_run is None:
                raise RuntimeError(f"Grader run {grader_run_id} not found in database")

            # Derive snapshot_slug from the graded critic run
            grader_config = grader_run.grader_config()
            graded_critic_run = session.get(AgentRun, grader_config.graded_agent_run_id)
            if graded_critic_run is None:
                raise RuntimeError(f"Graded critic run {grader_config.graded_agent_run_id} not found in database")
            snapshot_slug = graded_critic_run.critic_config().snapshot_slug
            typer.echo(f"Graded critic run {critic_run_id}")
            typer.echo(f"Grader run ID: {grader_run_id}")
            typer.echo(f"Snapshot: {snapshot_slug}")
            typer.echo(f"Status: {grader_run.status.value}")
            typer.echo("")

            # Display completion_summary if available
            if grader_run.completion_summary:
                typer.echo("Summary:")
                typer.echo(grader_run.completion_summary)
                typer.echo("")

            # Display recall metrics from grading_decisions
            if grader_run.status == AgentRunStatus.COMPLETED:
                # TODO: Deduplicate recall calculation into db/grading.py helper function
                total_credit = (
                    session.query(func.sum(GradingDecision.credit))
                    .filter_by(agent_run_id=grader_run_id)
                    .filter(GradingDecision.target_tp_id.isnot(None))
                    .scalar()
                    or 0.0
                )
                n_occurrences = (
                    session.query(GradingDecision.target_tp_id, GradingDecision.target_tp_occurrence_id)
                    .filter_by(agent_run_id=grader_run_id)
                    .filter(GradingDecision.target_tp_id.isnot(None))
                    .distinct()
                    .count()
                )
                recall = total_credit / n_occurrences if n_occurrences > 0 else 0.0
                typer.echo(f"Recall: {recall:.2%} ({total_credit:.1f} / {n_occurrences})")
    finally:
        await docker_client.close()


@app.command("grade-missing")
@async_run
async def cmd_grade_missing(
    grader_model: str = opt.OPT_GRADER_MODEL,
    max_parallel: int = opt.OPT_MAX_PARALLEL,
    verbose: bool = opt.OPT_VERBOSE,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Grade all critiques missing grader runs for the specified model.

    Finds critiques without a grader run for the given model and grades them
    in parallel with semaphore-limited concurrency.
    """
    docker_client = aiodocker.Docker()
    db_config = get_database_config()
    workspace_manager = WorkspaceManager.from_env()
    try:
        # Find critic run IDs missing grader runs for this model
        with get_session() as session:
            # Two-phase approach for unified AgentRun model
            # Phase 1: Get all completed critic runs
            completed_critic_runs = (
                session.query(AgentRun)
                .filter(
                    AgentRun.type_config["agent_type"].astext == AgentType.CRITIC,
                    AgentRun.status == AgentRunStatus.COMPLETED,
                )
                .all()
            )

            # Phase 2: Filter to those without grader runs for this model
            ungraded_critic_run_ids: list[UUID] = []
            for cr in completed_critic_runs:
                has_grader = (
                    session.query(AgentRun)
                    .filter(
                        AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
                        AgentRun.type_config["graded_agent_run_id"].astext == str(cr.agent_run_id),
                        AgentRun.model == grader_model,
                    )
                    .first()
                )
                if not has_grader:
                    ungraded_critic_run_ids.append(cr.agent_run_id)

            if not ungraded_critic_run_ids:
                typer.echo(f"No critic runs missing grader runs for model '{grader_model}'")
                return

            typer.echo(
                f"Found {len(ungraded_critic_run_ids)} critic runs missing grader runs for model '{grader_model}'"
            )
            typer.echo(f"Grading with max_parallel={max_parallel}...")

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_parallel)

        async def grade_one(critic_run_id: UUID) -> tuple[UUID, bool]:
            """Grade one critic run, returns (critic_run_id, success)"""
            async with semaphore:
                try:
                    with get_session() as session:
                        grader_run_id = await grade_critic_run_by_id(
                            session,
                            critic_run_id,
                            build_client(grader_model),
                            docker_client,
                            hydrator,
                            db_config,
                            workspace_manager=workspace_manager,
                            verbose=verbose,
                            max_turns=200,
                        )
                        if not verbose:
                            typer.echo(f"✓ Graded critic run {critic_run_id} → grader_run {grader_run_id}")
                        return (critic_run_id, True)
                except Exception as e:
                    typer.echo(f"✗ Failed to grade critic run {critic_run_id}: {e}", err=True)
                    return (critic_run_id, False)

        # Grade all in parallel (semaphore limits concurrency)
        results = await asyncio.gather(*[grade_one(cid) for cid in ungraded_critic_run_ids])

        # Summary
        successes = sum(1 for _, success in results if success)
        failures = sum(1 for _, success in results if not success)
        typer.echo("")
        typer.echo(f"Completed: {successes} succeeded, {failures} failed")
    finally:
        await docker_client.close()


@app.command("fix")
@async_run
async def cmd_fix(
    workdir: Path = opt.ARG_WORKDIR,
    scope: str = typer.Argument(..., help="Freeform scope description to enforce"),
    model: str = opt.OPT_MODEL,
    final_only: bool = opt.OPT_FINAL_ONLY,
    output_final_message: Path | None = opt.OPT_OUTPUT_FINAL_MESSAGE,
    skip_git_repo_check: bool = opt.OPT_SKIP_GIT_REPO_CHECK,
    full_auto: bool = opt.OPT_FULL_AUTO,
) -> None:
    """Refactor code within scope to satisfy property definitions (workspace-write sandbox)."""
    docker_client = aiodocker.Docker()
    try:
        schemas_json = build_input_schemas_json([Occurrence, LineRange])
        compositor = PropertiesDockerCompositor(
            workdir, docker_client, mount_properties=True, hydrator=SnapshotHydrator.from_env()
        )
        prompt = build_enforce_prompt(scope, compositor=compositor, schemas_json=schemas_json)
        cmd = build_cmd(
            model,
            workdir,
            BuildOptions(
                sandbox="workspace-write",
                skip_git_repo_check=skip_git_repo_check,
                full_auto=full_auto,
                extra_configs=['sandbox_permissions=["disk-full-read-access"]'],
            ),
        )
        if output_final_message:
            cmd.extend(["--output-last-message", str(output_final_message)])
        elif final_only:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                last_path = Path(tmp.name)
            cmd.extend(["--output-last-message", str(last_path)])

        # Use async subprocess to avoid blocking in async function
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _stdout, _stderr = await proc.communicate(input=prompt.encode("utf-8"))
        rc = proc.returncode if proc.returncode is not None else 1
        raise typer.Exit(code=rc)
    finally:
        await docker_client.close()


@app.command("lint-issue")
@async_run
async def cmd_lint_issue(
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    tp_id: str = typer.Argument(..., help="Issue id to lint (must have should_flag=true)"),
    occurrence: int = typer.Argument(..., help="0-based occurrence index"),
    model: str = opt.OPT_MODEL,
    dry_run: bool = opt.OPT_DRY_RUN,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    docker_client = aiodocker.Docker()
    try:
        rc = await run_specimen_lint_issue_async(
            snapshot,
            tp_id,
            model=model,
            dry_run=dry_run,
            occurrence_index=occurrence,
            client=build_client(model),
            docker_client=docker_client,
            hydrator=hydrator,
        )
        raise typer.Exit(code=rc)
    finally:
        await docker_client.close()


@app.command("eval-all")
@async_run
async def cmd_eval_all(hydrator: SnapshotHydrator = Depends(get_hydrator)) -> None:
    docker_client = aiodocker.Docker()
    try:
        await run_all_evals(
            client=build_client("gpt-5"), docker_client=docker_client, hydrator=hydrator, ctx=RunsContext.from_pkg_dir()
        )
    finally:
        await docker_client.close()


# GEPA command
app.command("gepa")(cmd_gepa)

# Stats command group
app.add_typer(stats_app, name="stats")

# Analyze exec commands
app.command("analyze-exec")(cmd_analyze_exec)

# Classify no-op commands
app.command("classify-noops")(cmd_classify_noops)

# Grade validation set command
app.command("grade-validation")(cmd_grade_validation)

# Speak with dead command
app.command("speak-with-dead")(cmd_speak_with_dead)


# ---------- Shared helpers for run ----------


@app.command("run")
@async_run
async def cmd_run(
    # Scope (required)
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    # Definition ID (required)
    definition_id: str = typer.Option(
        "critic", "--definition-id", "-d", help="Agent definition ID (e.g., 'critic', 'critic-v1'). Default: 'critic'."
    ),
    # File filtering
    files: list[str] | None = opt.OPT_FILES_FILTER,
    # Common options
    model: str = opt.OPT_MODEL,
    max_lines: int = opt.OPT_MAX_LINES,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Run critic agent on a snapshot with DB persistence.

    Uses AgentHandle to load agent definition from DB. The definition's AGENT.md
    provides the system prompt.

    Example:
        adgn-properties run ducktape/2025-11-26-00 --definition-id critic
    """
    docker_client = aiodocker.Docker()
    db_config = get_database_config()
    try:
        # Get available files from database (no hydration)
        with get_session() as session:
            snapshot_obj = session.query(Snapshot).filter_by(slug=snapshot).one()
            available_files = snapshot_obj.files_with_issues()

        # Filter files if requested
        available_files_dict = dict.fromkeys(available_files)
        files_spec = filter_files(available_files_dict, files)

        # Create workspace manager for this CLI run
        workspace_manager = WorkspaceManager.from_env()

        # Run critic using AgentHandle-based flow
        critic_run_id, status = await run_critic(
            definition_id=definition_id,
            snapshot_slug=snapshot,
            scope=files_spec,
            client=build_client(model),
            parent_agent_run_id=None,
            docker_client=docker_client,
            hydrator=hydrator,
            db_config=db_config,
            workspace_manager=workspace_manager,
            mount_properties=True,
            verbose=True,
            max_lines=max_lines,
            max_turns=100,
        )

        # Print results
        typer.echo("\n=== Critique Complete ===")
        typer.echo(f"Critic Run ID: {critic_run_id}")
        if status == AgentRunStatus.COMPLETED:
            critique_payload = _get_critique_payload(critic_run_id)
            typer.echo(f"Issues found: {len(critique_payload.issues)}")
            typer.echo(f"\n{critique_payload.model_dump_json(indent=2)}")
        else:
            typer.echo(f"Critic run ended with status: {status.value}", err=True)
    finally:
        await docker_client.close()
