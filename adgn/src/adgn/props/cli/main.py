"""Typer-based CLI entry for adgn-properties.

Incremental migration target: we will gradually move subcommands here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import contextlib
from dataclasses import dataclass
from importlib import resources
import logging
from pathlib import Path
import shutil
import tempfile
from typing import Annotated
from uuid import UUID

import aiodocker
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.traceback import install as rich_traceback_install
from sqlalchemy import distinct, func, select, tuple_
import typer
from typer_di import Depends, TyperDI

from adgn.cli.logging_callback import make_logging_callback
from adgn.cli_utils import async_run
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.bootstrap_capture import BootstrapCaptured, CapturingClient, format_bootstrap_output
from adgn.props.cli import common_options as opt
from adgn.props.cli.cmd_agent_definition import app as agent_definition_app
from adgn.props.cli.cmd_agent_helper import app as agent_helper_app
from adgn.props.cli.cmd_analyze_exec import cmd_analyze_exec
from adgn.props.cli.cmd_classify_noops import cmd_classify_noops
from adgn.props.cli.cmd_cluster_unknowns import app as cluster_unknowns_app
from adgn.props.cli.cmd_db import db_app
from adgn.props.cli.cmd_detector import cmd_detector_coverage, cmd_run_detector
from adgn.props.cli.cmd_gepa import cmd_gepa
from adgn.props.cli.cmd_grade_validation import cmd_grade_validation
from adgn.props.cli.cmd_snapshot import snapshot_app
from adgn.props.cli.cmd_speak_with_dead import cmd_speak_with_dead
from adgn.props.cli.cmd_stats import stats_app
from adgn.props.cli.resources import get_hydrator
from adgn.props.cli.shared import BuildOptions, build_cmd, filter_files
from adgn.props.cluster_unknowns import cluster_unknowns
from adgn.props.critic.critic import resolve_critic_scope, run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.critic.persistence import load_critic_submit_payload_mcp
from adgn.props.db import get_session, init_db
from adgn.props.db.config import get_database_config
from adgn.props.db.models import (
    CriticRun as DBCriticRun,
    CriticRunStatus,
    GraderRun as DBGraderRun,
    GraderRunStatus,
    GradingDecision,
    Prompt,
    Snapshot,
)
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.query_builders import PromptPerformanceRow, query_prompt_performance_stats, query_recall_by_example
from adgn.props.db.sync import get_specimens_base_path
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
from adgn.props.prompts.util import build_standard_context, get_templates_env
from adgn.props.runs_context import RunsContext
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


def _get_critique_payload(critic_run_id: UUID | None):
    """Query critique payload from critic run (reconstructed from normalized tables).

    Returns MCP CriticSubmitPayload with issues loaded from normalized tables.
    """
    assert critic_run_id is not None, "Critic run ID must not be None"
    with get_session() as session:
        critic_run = session.get(DBCriticRun, critic_run_id)
        assert critic_run is not None, f"Critic run {critic_run_id} not found"
        assert critic_run.status == CriticRunStatus.COMPLETED, (
            f"Critic run {critic_run_id} did not complete successfully (status: {critic_run.status})"
        )
        # Load MCP payload from normalized tables
        return load_critic_submit_payload_mcp(session, critic_run_id, notes_md=critic_run.completion_summary)


app = TyperDI(help="adgn-properties — properties tooling", add_completion=False)

# Subcommand groups
app.add_typer(db_app, name="db")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(cluster_unknowns_app, name="cluster-unknowns")
app.add_typer(agent_helper_app, name="agent-helper")
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


async def _run_snapshot_minicodex_async(
    snapshot: SnapshotSlug,
    *,
    dry_run: bool,
    embed_paths: list[Path] | None,
    mode: str,
    final_only: bool,
    output_final_message: Path | None,
    client: OpenAIModelProto,
    files: list[str] | None,
    hydrator: SnapshotHydrator,
    docker_client: aiodocker.Docker,
) -> int:
    db_config = get_database_config()

    # Get available files from database (no hydration)
    with get_session() as session:
        snapshot_obj = session.query(Snapshot).filter_by(slug=snapshot).one()
        available_files = snapshot_obj.files_with_issues()

    supplemental_text = read_embedded_paths(embed_paths) if embed_paths else None

    # Filter files if requested (returns CriticScopeSpec: sentinel or explicit set)
    # Convert set[Path] to dict for filter_files (which expects Mapping)
    available_files_dict = dict.fromkeys(available_files)
    files_spec = filter_files(available_files_dict, files)

    # Resolve files for prompt rendering
    resolved_files = await resolve_critic_scope(snapshot_slug=snapshot, files=files_spec)

    # Load preset template based on mode
    preset_name = {"discover": "discover", "open": "open", "find": "find"}[mode]
    prompt_raw = _load_preset_text(preset_name)

    # Create temporary workspace for compositor (only used for rendering, not execution)
    tmpdir = Path(tempfile.mkdtemp(prefix="props_cli_workspace_"))
    try:
        compositor = PropertiesDockerCompositor(tmpdir, docker_client, mount_properties=True, hydrator=hydrator)
        prompt = _render_prompt_with_context(
            prompt_raw, compositor=compositor, files=resolved_files, supplemental_text=supplemental_text
        )
    finally:
        # Clean up temp workspace
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Dry-run: save prompt and exit (before any agent/compositor setup)
    if dry_run:
        prompt_dir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = prompt_dir / f"codex_prompt_snapshot_{mode}.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        typer.echo(f"Prompt saved to: {prompt_file}")
        return 0

    # Use run_critic for structured execution and DB persistence
    critic_run_id, status = await run_critic(
        input_data=CriticInput(snapshot_slug=snapshot, scope=files_spec, prompt_sha256=hash_and_upsert_prompt(prompt)),
        client=client,
        hydrator=hydrator,
        db_config=db_config,
        prompt_optimization_run_id=None,
        docker_client=docker_client,
        mount_properties=True,
        verbose=True,
        max_turns=100,
    )

    # Handle max turns exceeded
    if status != CriticRunStatus.COMPLETED:
        typer.echo("Error: Critic exceeded max turns limit", err=True)
        return 1

    # Query critique data from database
    critique_payload = _get_critique_payload(critic_run_id)

    # Output final message if requested
    if output_final_message:
        output_final_message.write_text(critique_payload.model_dump_json(indent=2), encoding="utf-8")

    # Display results
    if not final_only:
        Console().print(render_to_rich(critique_payload))
    return 0


@app.command("snapshot-discover")
@async_run
async def cmd_snapshot_discover(
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    dry_run: bool = opt.OPT_DRY_RUN,
    final_only: bool = opt.OPT_FINAL_ONLY,
    output_final_message: Path | None = opt.OPT_OUTPUT_FINAL_MESSAGE,
    files: list[str] | None = opt.OPT_FILES_FILTER,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Discover only-new issues vs snapshot notes (covered/not_covered_yet)."""
    docker_client = aiodocker.Docker()
    try:
        # Get all snapshots from database
        with get_session() as session:
            all_snapshots = session.query(Snapshot).all()
            names = sorted([s.slug for s in all_snapshots])
        if snapshot not in names:
            typer.echo(f"Unknown snapshot slug: {snapshot}\nAvailable: \n" + "\n".join(f" - {n}" for n in names))
            raise typer.Exit(2)
        # TODO: Remove this manual path wrangling. The covered.md/not_covered_yet.md files
        # should be deprecated and removed, along with snapshot-discover command and related paths.
        spec_dir = get_specimens_base_path() / snapshot
        embed_paths: list[Path] | None = [
            p for p in [spec_dir / "covered.md", spec_dir / "not_covered_yet.md"] if p.exists()
        ]
        if not embed_paths:
            embed_paths = None
        rc = await _run_snapshot_minicodex_async(
            snapshot,
            dry_run=dry_run,
            embed_paths=embed_paths,
            mode="discover",
            final_only=final_only,
            output_final_message=output_final_message,
            client=build_client("gpt-5"),
            files=files,
            hydrator=hydrator,
            docker_client=docker_client,
        )
        raise typer.Exit(code=rc)
    finally:
        await docker_client.close()


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
            ctx=RunsContext.from_pkg_dir(),
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
    def select_pareto_examples(session, prompt_sha256_param: str, limit: int) -> list[tuple[SnapshotSlug, str | None]]:
        """Select Pareto-optimal training examples for a prompt."""
        # Query occurrence-weighted recall per example using helper
        results = query_recall_by_example(session, split=Split.TRAIN, prompt_sha256=prompt_sha256_param)

        if not results:
            raise ValueError(f"No grader runs found for prompt {short_sha(prompt_sha256_param)}")

        # Build example scores dict
        example_scores: dict[tuple[SnapshotSlug, str | None], float] = {}
        for row in results:
            key = (row.snapshot_slug, row.scope_hash)
            example_scores[key] = row.recall

        # Sort by recall descending and take top N
        sorted_examples = sorted(example_scores.items(), key=lambda x: x[1], reverse=True)
        top_n = sorted_examples[:limit]
        logger.info(
            f"Selected {len(top_n)} Pareto-optimal examples (recall range: {top_n[-1][1]:.1%} to {top_n[0][1]:.1%})"
        )
        return [key for key, _score in top_n]

    # 1. Load current prompt
    console.print("[dim]Loading prompt from database...[/dim]")
    with get_session() as session:
        if prompt_sha256:
            # Explicit prompt specified - verify it has enough training examples
            prompt = session.query(Prompt).filter_by(prompt_sha256=prompt_sha256).first()
            if not prompt:
                console.print(f"[red]Error:[/red] Prompt not found: {prompt_sha256}")
                raise typer.Exit(1)
            prompt_text = prompt.prompt_text

            # Count training examples with grader runs for this prompt
            grader_runs = (
                session.query(DBCriticRun, DBGraderRun)
                .join(DBGraderRun, DBCriticRun.id == DBGraderRun.critic_run_id)
                .join(Snapshot, DBCriticRun.snapshot_slug == Snapshot.slug)
                .filter(DBCriticRun.prompt_sha256 == prompt_sha256, Snapshot.split == Split.TRAIN)
                .all()
            )

            if len(grader_runs) < n_examples:
                console.print(
                    f"[red]Error:[/red] Prompt {short_sha(prompt_sha256)} has only {len(grader_runs)} "
                    f"training examples with grader runs (need {n_examples})"
                )
                raise typer.Exit(1)

            console.print(
                f"[green]✓[/green] Loaded prompt: {short_sha(prompt_sha256)} "
                f"({len(grader_runs)} training examples available)"
            )
        else:
            # Auto-select: find prompts with enough training examples, pick best by validation LCB
            # Count training examples per prompt
            prompt_example_counts = (
                session.query(
                    DBCriticRun.prompt_sha256,
                    func.count(distinct(tuple_(DBCriticRun.snapshot_slug, DBCriticRun.scope_hash))).label(
                        "example_count"
                    ),
                )
                .join(DBGraderRun, DBCriticRun.id == DBGraderRun.critic_run_id)
                .join(Snapshot, DBCriticRun.snapshot_slug == Snapshot.slug)
                .filter(Snapshot.split == Split.TRAIN)
                .group_by(DBCriticRun.prompt_sha256)
                .having(func.count(distinct(tuple_(DBCriticRun.snapshot_slug, DBCriticRun.scope_hash))) >= n_examples)
                .all()
            )

            if not prompt_example_counts:
                console.print(f"[red]Error:[/red] No prompts have {n_examples}+ training examples with grader runs")
                raise typer.Exit(1)

            eligible_sha256s = {p for p, _ in prompt_example_counts}

            # Get performance stats for eligible prompts
            stats = query_prompt_performance_stats(session, limit=100)
            # Get validation stats for whole-snapshot examples
            valid_stats_key = (Split.VALID, "entire_snapshot")
            eligible_stats = [
                s
                for s in stats
                if s.prompt_sha256 in eligible_sha256s
                and valid_stats_key in s.stats
                and s.stats[valid_stats_key].success_count > 0
            ]

            if not eligible_stats:
                console.print(
                    f"[red]Error:[/red] No prompts with {n_examples}+ training examples have validation results"
                )
                raise typer.Exit(1)

            # Pick best by validation LCB (whole-snapshot)
            def get_lcb(s: PromptPerformanceRow) -> float:
                lcb = s.stats[valid_stats_key].lcb
                return lcb if lcb is not None else -1.0

            best = max(eligible_stats, key=get_lcb)
            prompt_sha256 = best.prompt_sha256
            prompt = session.query(Prompt).filter_by(prompt_sha256=prompt_sha256).first()
            if not prompt:
                console.print(f"[red]Error:[/red] Prompt metadata missing: {prompt_sha256}")
                raise typer.Exit(1)

            example_count = next(count for p, count in prompt_example_counts if p == prompt_sha256)
            prompt_text = prompt.prompt_text
            console.print(
                f"[green]✓[/green] Selected best prompt: {short_sha(prompt_sha256)} ({example_count} training examples)"
            )

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
        example_keys = select_pareto_examples(session, prompt_sha256, n_examples)
        if not example_keys:
            console.print("[red]Error:[/red] No training examples found")
            raise typer.Exit(1)

        if len(example_keys) < n_examples:
            console.print(
                f"[yellow]Warning:[/yellow] Only {len(example_keys)} examples available (requested {n_examples})"
            )

        console.print(f"[green]✓[/green] Selected {len(example_keys)} examples")

        table = Table(title="Training Examples")
        table.add_column("Snapshot", style="cyan")
        table.add_column("Scope Hash", style="dim")
        for slug, scope_hash in example_keys[:5]:
            assert scope_hash is not None
            table.add_row(slug, short_sha(scope_hash))
        if len(example_keys) > 5:
            table.add_row("[dim]...[/dim]", f"[dim](+{len(example_keys) - 5} more)[/dim]")
        console.print(table)

    # 3. Run improvement agent
    console.print("\n[bold]Running improvement agent[/bold]")
    console.print(f"  Model: {model}")
    console.print(f"  Token budget: {token_budget:,}")
    console.print(f"  Examples: {len(example_keys)}")
    console.print()

    docker_client = aiodocker.Docker()
    db_config = get_database_config()
    openai_client = build_client(model)
    try:
        result = await run_improvement_agent(
            examples=example_keys,
            current_prompt=prompt_text,
            token_budget=token_budget,
            model=model,
            hydrator=hydrator,
            docker_client=docker_client,
            db_config=db_config,
            client=openai_client,
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

    # 4. Display results
    console.print()
    if isinstance(result.outcome, OutcomeSuccess):
        # Persist to database
        prompt_sha256 = hash_and_upsert_prompt(result.outcome.submission.prompt_text)

        panel = Panel(
            f"[green]✓ Prompt submitted successfully[/green]\n\n"
            f"[bold]Prompt SHA256:[/bold] {prompt_sha256}\n\n"
            f"[bold]Tokens:[/bold] {result.tokens_used:,} / {token_budget:,} "
            f"({100 * result.tokens_used / token_budget:.1f}%)\n\n"
            f"[bold]Rationale:[/bold]\n{result.outcome.submission.rationale}\n\n"
            f"[bold]Expected improvement:[/bold]\n{result.outcome.submission.expected_improvement}\n\n"
            f"[bold]Prompt length:[/bold] {len(result.outcome.submission.prompt_text):,} characters",
            title="Improvement Result",
            border_style="green",
        )
        console.print(panel)

        # Display prompt text
        console.print("\n[bold cyan]Improved Prompt:[/bold cyan]\n")
        console.print(Panel(result.outcome.submission.prompt_text, border_style="dim"))
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
                verbose=verbose,
                max_turns=200,
            )
            db_grader_run = session.get(DBGraderRun, grader_run_id)
            if db_grader_run is None:
                raise RuntimeError(f"Grader run {grader_run_id} not found in database")

            typer.echo(f"Graded critic run {critic_run_id}")
            typer.echo(f"Grader run ID: {grader_run_id}")
            typer.echo(f"Grader run transcript_id: {db_grader_run.transcript_id}")
            typer.echo(f"Snapshot: {db_grader_run.snapshot_slug}")
            typer.echo(f"Status: {db_grader_run.status.value}")
            typer.echo("")

            # Display notes_md if available
            if db_grader_run.notes_md:
                typer.echo("Summary:")
                typer.echo(db_grader_run.notes_md)
                typer.echo("")

            # Display recall metrics from grading_decisions
            if db_grader_run.status == GraderRunStatus.COMPLETED:
                # TODO: Deduplicate recall calculation into db/grading.py helper function
                total_credit = (
                    session.query(func.sum(GradingDecision.credit))
                    .filter_by(grader_run_id=grader_run_id)
                    .filter(GradingDecision.target_tp_id.isnot(None))
                    .scalar()
                    or 0.0
                )
                n_occurrences = (
                    session.query(GradingDecision.target_tp_id, GradingDecision.target_tp_occurrence_id)
                    .filter_by(grader_run_id=grader_run_id)
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
    try:
        # Find critic run IDs missing grader runs for this model
        with get_session() as session:
            # More efficient than NOT IN: LEFT JOIN with NULL check
            # Only grade successful critic runs (filter by status)
            ungraded_critic_run_ids = (
                session.execute(
                    select(DBCriticRun.id)
                    .outerjoin(
                        DBGraderRun, (DBGraderRun.critic_run_id == DBCriticRun.id) & (DBGraderRun.model == grader_model)
                    )
                    .where(
                        DBGraderRun.id.is_(None),  # No grader run exists for this model
                        DBCriticRun.status == CriticRunStatus.COMPLETED,  # Only completed critic runs
                    )
                )
                .scalars()
                .all()
            )

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


# Detector commands
app.command("run-detector")(cmd_run_detector)
app.command("detector-coverage")(cmd_detector_coverage)

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


def _render_prompt_with_context(
    text: str, *, compositor: PropertiesDockerCompositor, files: Iterable[Path], supplemental_text: str | None = None
) -> str:
    """Render a (potentially Jinja) prompt with standard props context; plain text passes through.

    Args:
        text: Template text (Jinja or plain)
        compositor: Docker compositor with configuration
        files: File paths for scope
        supplemental_text: Optional additional context

    Returns:
        Rendered prompt text
    """
    env = get_templates_env()
    tmpl = env.from_string(text)
    context = build_standard_context(files=files, compositor=compositor, supplemental_text=supplemental_text)
    return str(tmpl.render(**context))


# --- Unified run command (always structured; preset/prompt-file/text) ---

_PRESET_MAP: dict[str, str] = {
    # General review styles
    "open": "prompts/open.j2.md",
    "find": "prompts/find.j2.md",
    "discover": "prompts/discover.j2.md",
    # High-volume structured critic
    "max-recall-critic": "prompts/max_recall_critic.j2.md",
}


def _print_presets() -> None:
    for name in sorted(_PRESET_MAP.keys()):
        print(name)


def _load_preset_text(name: str) -> str:
    if not (rel := _PRESET_MAP.get(name)):
        raise typer.BadParameter(f"Unknown preset: {name}. Use 'adgn-properties list-presets' to see options.")
    # Resources are relative to the adgn.props package root
    res = resources.files("adgn.props").joinpath(rel)
    try:
        return res.read_text(encoding="utf-8")
    except Exception as e:
        raise typer.BadParameter(f"Failed to load preset '{name}' from resources: {rel} ({e})") from e


# (Jinja rendering helpers are inlined at call sites; plain Markdown passes through unchanged)


@app.command("run")
@async_run
async def cmd_run(
    # Scope (required)
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    # Prompt source (at most one; default: max-recall-critic)
    preset: str | None = typer.Option(
        None, "--preset", help="Built-in prompt name; see 'adgn-properties list-presets'"
    ),
    prompt_file: Path | None = typer.Option(None, "--prompt-file", exists=True, dir_okay=False, readable=True),
    prompt_text: str | None = typer.Option(
        None, "--prompt-text", help="Inline prompt text (discouraged for long prompts)"
    ),
    # File filtering
    files: list[str] | None = opt.OPT_FILES_FILTER,
    # Common options
    model: str = opt.OPT_MODEL,
    dry_run: bool = typer.Option(
        False, help="Capture first API request (tools, instructions, inputs) and print JSON; don't call LLM"
    ),
    max_lines: int = opt.OPT_MAX_LINES,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Run structured critic on a snapshot with DB persistence.

    Default preset: max-recall-critic. Prints critique JSON on completion.
    """
    docker_client = aiodocker.Docker()
    db_config = get_database_config()
    try:
        # Validate prompt source
        sources = [x is not None for x in (preset, prompt_file, prompt_text)]
        if sum(sources) == 0:
            preset = "max-recall-critic"
        elif sum(sources) > 1:
            print("ERROR: Provide at most one of --preset, --prompt-file, or --prompt-text.")
            raise typer.Exit(2)

        # Resolve prompt content
        if preset is not None:
            prompt_raw = _load_preset_text(preset)
        elif prompt_file is not None:
            prompt_raw = prompt_file.read_text(encoding="utf-8")
        else:
            prompt_raw = prompt_text or ""

        # Get available files from database (no hydration)
        with get_session() as session:
            snapshot_obj = session.query(Snapshot).filter_by(slug=snapshot).one()
            available_files = snapshot_obj.files_with_issues()

        # Filter files if requested
        available_files_dict = dict.fromkeys(available_files)
        files_spec = filter_files(available_files_dict, files)
        resolved_files = await resolve_critic_scope(snapshot_slug=snapshot, files=files_spec)

        # Create temporary workspace for compositor (only used for rendering, not execution)
        workspace_tmpdir = Path(tempfile.mkdtemp(prefix="props_cli_workspace_"))
        try:
            compositor = PropertiesDockerCompositor(
                workspace_tmpdir, docker_client, mount_properties=True, hydrator=hydrator, ephemeral=False
            )
            prompt = _render_prompt_with_context(prompt_raw, compositor=compositor, files=resolved_files)
        finally:
            # Clean up temp workspace
            shutil.rmtree(workspace_tmpdir, ignore_errors=True)

        # Build client - CapturingClient for dry_run, real client otherwise
        if dry_run:
            capturing_client = CapturingClient()
            with contextlib.suppress(BootstrapCaptured):
                await run_critic(
                    input_data=CriticInput(
                        snapshot_slug=snapshot, scope=files_spec, prompt_sha256=hash_and_upsert_prompt(prompt)
                    ),
                    client=capturing_client,
                    hydrator=hydrator,
                    db_config=db_config,
                    prompt_optimization_run_id=None,
                    docker_client=docker_client,
                    mount_properties=True,
                    verbose=False,
                    max_lines=max_lines,
                    max_turns=1,
                )

            if capturing_client.captured is None:
                typer.echo("[ERROR] No request captured - agent exited before first API call", err=True)
                raise typer.Exit(1)

            typer.echo(format_bootstrap_output(capturing_client.captured))
            return

        # Run critic with DB persistence
        critic_run_id, status = await run_critic(
            input_data=CriticInput(
                snapshot_slug=snapshot, scope=files_spec, prompt_sha256=hash_and_upsert_prompt(prompt)
            ),
            client=build_client(model),
            hydrator=hydrator,
            db_config=db_config,
            prompt_optimization_run_id=None,
            docker_client=docker_client,
            mount_properties=True,
            verbose=True,
            max_lines=max_lines,
            max_turns=100,
        )

        # Print results
        typer.echo("\n=== Critique Complete ===")
        typer.echo(f"Critic Run ID: {critic_run_id}")
        if status == CriticRunStatus.COMPLETED:
            # Query critique data from database
            critique_payload = _get_critique_payload(critic_run_id)

            typer.echo(f"Issues found: {len(critique_payload.issues)}")
            typer.echo(f"\n{critique_payload.model_dump_json(indent=2)}")
        else:
            typer.echo("Critic exceeded max turns limit", err=True)
    finally:
        await docker_client.close()


@app.command("list-presets")
def cmd_list_presets() -> None:
    """List available built-in prompt presets and their descriptions."""
    _print_presets()
