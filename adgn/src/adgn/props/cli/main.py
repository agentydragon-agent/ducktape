"""Typer-based CLI entry for adgn-properties.

Incremental migration target: we will gradually move subcommands here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources
import logging
from pathlib import Path
import subprocess
import tempfile
from typing import Annotated
from uuid import UUID

from fastmcp.client import Client
from rich.console import Console
from rich.traceback import install as rich_traceback_install
from sqlalchemy import select
import typer

from adgn.agent.agent import MiniCodex
from adgn.agent.display import DisplayEventsHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.llm.logging_config import VALID_LOG_LEVELS, configure_logging
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.cli import common_options as opt
from adgn.props.cli.cmd_db import cmd_db_recreate, cmd_sync
from adgn.props.cli.cmd_detector import cmd_detector_coverage, cmd_run_detector
from adgn.props.cli.cmd_gepa import cmd_gepa
from adgn.props.cli.cmd_snapshot import cmd_snapshot_list, snapshot_capture_ducktape, snapshot_dump, snapshot_exec
from adgn.props.cli.cmd_speak_with_dead import cmd_speak_with_dead
from adgn.props.cli.cmd_stats import cmd_stats
from adgn.props.cli.decorators import async_run
from adgn.props.cli.shared import BuildOptions, build_cmd, run_check_minicodex_async, save_prompt_to_tmp
from adgn.props.cluster_unknowns import cluster_unknowns
from adgn.props.critic.critic import resolve_critic_scope, run_critic
from adgn.props.critic.models import ALL_FILES_WITH_ISSUES, CriticInput
from adgn.props.db import get_session, init_db
from adgn.props.db.models import Critique, GraderRun as DBGraderRun, Snapshot
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.sync import get_specimens_base_path
from adgn.props.docker_env import PropertiesDockerWiring, properties_docker_spec
from adgn.props.eval_harness import run_all_evals
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.ids import SnapshotSlug
from adgn.props.lint_issue import run_specimen_lint_issue_async
from adgn.props.models.critic_scopes import CriticScopeSpec
from adgn.props.models.true_positive import IssueCore, LineRange, Occurrence
from adgn.props.prompt_optimizer import run_prompt_optimizer
from adgn.props.prompts.builder import build_enforce_prompt
from adgn.props.prompts.schemas import build_input_schemas_json
from adgn.props.prompts.util import build_standard_context, enumerate_files_from_path, get_templates_env
from adgn.props.runs_context import RunsContext, format_timestamp_session
from adgn.props.snapshot_hydrator import SnapshotHydrator

# Reduce Rich traceback verbosity for CLI errors
rich_traceback_install(show_locals=False, max_frames=12, extra_lines=1, width=100)

logger = logging.getLogger(__name__)

app = typer.Typer(help="adgn-properties (Typer) — properties tooling", add_completion=False)

# Subcommand groups
db_app = typer.Typer(help="Database management commands")
app.add_typer(db_app, name="db")

snapshot_app = typer.Typer(help="Snapshot commands")
app.add_typer(snapshot_app, name="snapshot")


@app.callback()
def _init_logging(
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
            "--log-level", envvar="ADGN_LOG_LEVEL", help=f"Log level: {', '.join(VALID_LOG_LEVELS)} (default: WARNING)"
        ),
    ] = "WARNING",
) -> None:
    """Global callback to configure logging for all subcommands."""
    configure_logging(log_output=log_output, log_level=log_level)
    # Reduce Rich traceback verbosity for CLI errors
    rich_traceback_install(show_locals=False, max_frames=12, extra_lines=1, width=100)


@dataclass
class MetricsRow:
    iteration: int
    mean_recall: float
    tp: int
    fp: int
    fn: int
    unknown: int
    dir: str


@app.command("check")
@async_run
async def cmd_check(
    workdir: Path = opt.ARG_WORKDIR,
    scope: str = opt.ARG_SCOPE,
    model: str = opt.OPT_MODEL,
    dry_run: bool = opt.OPT_DRY_RUN,
    final_only: bool = opt.OPT_FINAL_ONLY,
    output_final_message: Path | None = opt.OPT_OUTPUT_FINAL_MESSAGE,
    allow_general_findings: bool = opt.OPT_ALLOW_GENERAL,
) -> None:
    """Check a static path set against committed property definitions (docker RO mount)."""

    # Determine preset based on mode
    preset_name = "open" if allow_general_findings else "find"
    prompt_raw = _load_preset_text(preset_name)

    wiring = properties_docker_spec(workdir, mount_properties=True)
    files = enumerate_files_from_path(workdir)
    prompt_text = _render_prompt_with_context(prompt_raw, wiring=wiring, files=files, supplemental_text=scope)

    # Dry-run: save prompt and exit
    if dry_run:
        save_prompt_to_tmp("codex_prompt_check", prompt_text)
        return

    rc = await run_check_minicodex_async(
        workdir,
        prompt_text,
        model=model,
        output_final_message=output_final_message,
        final_only=final_only,
        client=build_client(model),
    )
    raise typer.Exit(code=rc)


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


def _filter_files(all_files: Mapping[Path, object], requested_files: list[str] | None) -> CriticScopeSpec:
    """Filter available files to requested subset, with validation.

    Args:
        all_files: All available files from snapshot
        requested_files: Optional list of relative paths to filter to

    Returns:
        ALL_FILES_WITH_ISSUES sentinel if no filter requested,
        otherwise validated set of requested paths

    Raises:
        typer.Exit: If requested files are invalid or not found
    """
    # No filter → return sentinel for downstream resolution
    if requested_files is None:
        return ALL_FILES_WITH_ISSUES

    # Validate requested files exist
    available = set(all_files.keys())
    requested_set = {Path(f) for f in requested_files}
    invalid = requested_set - available

    if invalid:
        typer.echo("Error: The following files are not in the snapshot:", err=True)
        for f in sorted(str(p) for p in invalid):
            typer.echo(f"  - {f}", err=True)
        typer.echo(f"\nAvailable files ({len(all_files)}):", err=True)
        for f in sorted(str(p) for p in all_files)[:10]:
            typer.echo(f"  - {f}", err=True)
        if len(all_files) > 10:
            typer.echo(f"  ... and {len(all_files) - 10} more", err=True)
        raise typer.Exit(1)

    # Return validated requested files
    return requested_set & available


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
) -> int:
    # Hydrate snapshot source code (issues loaded from DB elsewhere)
    async with hydrator.hydrate(snapshot) as hydrated:
        supplemental_text = read_embedded_paths(embed_paths) if embed_paths else None

        # Filter files if requested (returns CriticScopeSpec: sentinel or explicit set)
        files_spec = _filter_files(hydrated.all_discovered_files, files)

        # Resolve files for prompt rendering
        resolved_files = await resolve_critic_scope(snapshot_slug=snapshot, files=files_spec)

        # Load preset template based on mode
        preset_name = {"discover": "discover", "open": "open", "find": "find"}[mode]
        prompt_raw = _load_preset_text(preset_name)

        wiring = properties_docker_spec(hydrated.content_root, mount_properties=True)
        prompt = _render_prompt_with_context(
            prompt_raw, wiring=wiring, files=resolved_files, supplemental_text=supplemental_text
        )

        # Dry-run: save prompt and exit (before any agent/compositor setup)
        if dry_run:
            tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
            tmpdir.mkdir(parents=True, exist_ok=True)
            prompt_file = tmpdir / f"codex_prompt_snapshot_{mode}.md"
            prompt_file.write_text(prompt, encoding="utf-8")
            typer.echo(f"Prompt saved to: {prompt_file}")
            return 0

        # Use run_critic for structured execution and DB persistence
        critic_output, _critic_run_id, _critique_id = await run_critic(
            input_data=CriticInput(
                snapshot_slug=snapshot, files=files_spec, prompt_sha256=hash_and_upsert_prompt(prompt)
            ),
            client=client,
            content_root=hydrated.content_root,
            mount_properties=True,
            verbose=True,
        )

        # Output final message if requested
        if output_final_message:
            output_final_message.write_text(critic_output.result.model_dump_json(indent=2), encoding="utf-8")

        # Display results
        if not final_only:
            Console().print(render_to_rich(critic_output.result))
        return 0


@app.command("snapshot-discover")
@async_run
async def cmd_snapshot_discover(
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    dry_run: bool = opt.OPT_DRY_RUN,
    final_only: bool = opt.OPT_FINAL_ONLY,
    output_final_message: Path | None = opt.OPT_OUTPUT_FINAL_MESSAGE,
    files: list[str] | None = opt.OPT_FILES_FILTER,
) -> None:
    """Discover only-new issues vs snapshot notes (covered/not_covered_yet)."""
    hydrator = SnapshotHydrator.from_package_resources()
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
    )
    raise typer.Exit(code=rc)


@app.command("cluster-unknowns")
@async_run
async def cmd_cluster_unknowns(model: str = opt.OPT_MODEL, out_dir: Path | None = opt.OPT_OUTPUT_DIR) -> None:
    """Cluster all 'unknown' issues across all prompt_optimize runs via an in-proc MCP tool.

    The agent must submit a single payload of clusters: [{name: str, true_positives: [uid,...]}].
    """
    init_db()
    root = await cluster_unknowns(model=model, out_dir=out_dir, ctx=RunsContext.from_pkg_dir())
    typer.echo(f"Clusters written to: {root}/<snapshot>/clusters.json")


@app.command("prompt-optimize")
@async_run
async def prompt_optimize(
    budget: float = typer.Option(50.0, "--budget", help="$ budget for optimization"),
    model: str = opt.OPT_MODEL,
    verbose: bool = opt.OPT_VERBOSE,
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt using prompt_eval MCP with $ budget."""
    init_db()
    hydrator = SnapshotHydrator.from_package_resources()
    await run_prompt_optimizer(
        budget=budget, ctx=RunsContext.from_pkg_dir(), hydrator=hydrator, model=model, verbose=verbose
    )


@app.command("snapshot-grade")
@async_run
async def snapshot_grade(
    critique_id: str = typer.Argument(..., help="Critique ID (UUID) from database"),
    model: str = opt.OPT_MODEL,
    verbose: bool = opt.OPT_VERBOSE,
) -> None:
    """Grade a critique by database ID against canonical findings.

    Fetches critique from database, executes grader, and persists results.
    """
    init_db()

    # Query database and grade critique in single session
    with get_session() as session:
        grader_run_id = await grade_critique_by_id(session, UUID(critique_id), build_client(model), verbose=verbose)
        db_grader_run = session.get(DBGraderRun, grader_run_id)
        if db_grader_run is None:
            raise RuntimeError(f"Grader run {grader_run_id} not found in database")

        # db_grader_run.output is now typed as GraderOutput (PydanticColumn)
        typer.echo(f"Graded critique {critique_id}")
        typer.echo(f"Grader run ID: {grader_run_id}")
        typer.echo(f"Grader run transcript_id: {db_grader_run.transcript_id}")
        typer.echo(f"Snapshot: {db_grader_run.snapshot_slug}")
        typer.echo("")
        typer.echo(db_grader_run.output.model_dump_json(indent=2))


@app.command("grade-missing")
@async_run
async def cmd_grade_missing(
    model: str = typer.Option("gpt-5.1-codex-mini", "--model", help="Grader model to use"),
    max_parallel: int = typer.Option(1, "--max-parallel", help="Maximum number of parallel grader runs"),
    verbose: bool = opt.OPT_VERBOSE,
) -> None:
    """Grade all critiques missing grader runs for the specified model.

    Finds critiques without a grader run for the given model and grades them
    in parallel with semaphore-limited concurrency.
    """
    init_db()

    # Find critique IDs missing grader runs for this model
    with get_session() as session:
        # More efficient than NOT IN: LEFT JOIN with NULL check
        # Also filter out critiques with NULL payload (failed critic runs)
        ungraded_critique_ids = (
            session.execute(
                select(Critique.id)
                .outerjoin(DBGraderRun, (DBGraderRun.critique_id == Critique.id) & (DBGraderRun.model == model))
                .where(
                    DBGraderRun.id.is_(None),  # No grader run exists for this model
                    Critique.payload.is_not(None),  # Payload is not SQL NULL
                )
            )
            .scalars()
            .all()
        )

        if not ungraded_critique_ids:
            typer.echo(f"No critiques missing grader runs for model '{model}'")
            return

        typer.echo(f"Found {len(ungraded_critique_ids)} critiques missing grader runs for model '{model}'")
        typer.echo(f"Grading with max_parallel={max_parallel}...")

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_parallel)

    async def grade_one(critique_id: UUID) -> tuple[UUID, bool]:
        """Grade one critique, returns (critique_id, success)"""
        async with semaphore:
            try:
                with get_session() as session:
                    grader_run_id = await grade_critique_by_id(
                        session, critique_id, build_client(model), verbose=verbose
                    )
                    if not verbose:
                        typer.echo(f"✓ Graded critique {critique_id} → grader_run {grader_run_id}")
                    return (critique_id, True)
            except Exception as e:
                typer.echo(f"✗ Failed to grade critique {critique_id}: {e}", err=True)
                return (critique_id, False)

    # Grade all in parallel (semaphore limits concurrency)
    results = await asyncio.gather(*[grade_one(cid) for cid in ungraded_critique_ids])

    # Summary
    successes = sum(1 for _, success in results if success)
    failures = sum(1 for _, success in results if not success)
    typer.echo("")
    typer.echo(f"Completed: {successes} succeeded, {failures} failed")


@app.command("fix")
def cmd_fix(
    workdir: Path = opt.ARG_WORKDIR,
    scope: str = typer.Argument(..., help="Freeform scope description to enforce"),
    model: str = opt.OPT_MODEL,
    final_only: bool = opt.OPT_FINAL_ONLY,
    output_final_message: Path | None = opt.OPT_OUTPUT_FINAL_MESSAGE,
    skip_git_repo_check: bool = opt.OPT_SKIP_GIT_REPO_CHECK,
    full_auto: bool = opt.OPT_FULL_AUTO,
) -> None:
    """Refactor code within scope to satisfy property definitions (workspace-write sandbox)."""

    schemas_json = build_input_schemas_json([Occurrence, LineRange, IssueCore])
    wiring = properties_docker_spec(workdir, mount_properties=True)
    prompt = build_enforce_prompt(scope, wiring=wiring, schemas_json=schemas_json)
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
    rc = subprocess.run(cmd, check=False, input=prompt, text=True).returncode
    raise typer.Exit(code=rc)


@app.command("lint-issue")
@async_run
async def cmd_lint_issue(
    snapshot: SnapshotSlug = opt.ARG_SNAPSHOT,
    tp_id: str = typer.Argument(..., help="Issue id to lint (must have should_flag=true)"),
    occurrence: int = typer.Argument(..., help="0-based occurrence index"),
    model: str = opt.OPT_MODEL,
    dry_run: bool = opt.OPT_DRY_RUN,
) -> None:
    hydrator = SnapshotHydrator.from_package_resources()
    rc = await run_specimen_lint_issue_async(
        snapshot,
        tp_id,
        model=model,
        dry_run=dry_run,
        occurrence_index=occurrence,
        client=build_client(model),
        hydrator=hydrator,
    )
    raise typer.Exit(code=rc)


@app.command("eval-all")
@async_run
async def cmd_eval_all() -> None:
    hydrator = SnapshotHydrator.from_package_resources()
    await run_all_evals(client=build_client("gpt-5"), hydrator=hydrator, ctx=RunsContext.from_pkg_dir())


# DB commands
db_app.command("sync")(cmd_sync)
db_app.command("recreate")(cmd_db_recreate)

# Snapshot commands
snapshot_app.command("list")(cmd_snapshot_list)
snapshot_app.command("dump")(snapshot_dump)
snapshot_app.command("exec")(snapshot_exec)
snapshot_app.command("capture-ducktape")(snapshot_capture_ducktape)

# Detector commands
app.command("run-detector")(cmd_run_detector)
app.command("detector-coverage")(cmd_detector_coverage)

# GEPA command
app.command("gepa")(cmd_gepa)

# Stats command
app.command("stats")(cmd_stats)

# Speak with dead command
app.command("speak-with-dead")(cmd_speak_with_dead)


# ---------- Shared helpers for run ----------


def _render_prompt_with_context(
    text: str, *, wiring: PropertiesDockerWiring, files: Iterable[Path], supplemental_text: str | None = None
) -> str:
    """Render a (potentially Jinja) prompt with standard props context; plain text passes through.

    Args:
        text: Template text (Jinja or plain)
        wiring: Docker wiring config
        files: File paths for scope
        supplemental_text: Optional additional context

    Returns:
        Rendered prompt text
    """
    env = get_templates_env()
    tmpl = env.from_string(text)
    context = build_standard_context(files=files, wiring=wiring, supplemental_text=supplemental_text)
    return str(tmpl.render(**context))


@asynccontextmanager
async def _open_run_context(
    path: Path | None, snapshot: SnapshotSlug | None, files: list[str] | None, hydrator: SnapshotHydrator
):
    """Yield (wiring, files_spec, label) for either a local path or a hydrated snapshot.

    Args:
        path: Local directory path (mutually exclusive with snapshot)
        snapshot: Snapshot slug (mutually exclusive with path)
        files: Optional file filter (only for snapshots)
        hydrator: SnapshotHydrator instance (for source code extraction)

    Yields:
        (wiring, files_spec, label) tuple where files_spec is CriticScopeSpec
    """
    if path is not None:
        wiring = properties_docker_spec(path, mount_properties=True, ephemeral=False)
        all_files = enumerate_files_from_path(path)
        yield wiring, all_files, path.name
        return
    # Hydrate snapshot source code (issues loaded from DB elsewhere)
    assert snapshot is not None, "snapshot must be provided if path is None"
    async with hydrator.hydrate(snapshot) as hydrated:
        wiring = properties_docker_spec(hydrated.content_root, mount_properties=True, ephemeral=False)
        files_spec = _filter_files(hydrated.all_discovered_files, files)
        yield wiring, files_spec, snapshot


async def _exec_agent(
    *,
    wiring: PropertiesDockerWiring,
    prompt_text: str,
    model: str,
    structured: bool,
    output_final_message: Path | None,
    final_only: bool,
    label: str,
    snapshot_slug: SnapshotSlug | None,
    files_spec: CriticScopeSpec | None,
    dry_run: bool = False,
) -> None:
    # Dry-run: save prompt and exit (before any agent/DB/compositor setup)
    if dry_run:
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        prompt_file = tmpdir / f"codex_prompt_{label}.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt_text, encoding="utf-8")
        typer.echo(f"Prompt saved to: {prompt_file}")
        return

    # Structured mode: use run_critic for execution and DB persistence
    if structured:
        assert snapshot_slug is not None, "structured mode requires snapshot_slug"
        assert files_spec is not None, "structured mode requires files_spec"
        critic_output, _critic_run_id, _critique_id = await run_critic(
            input_data=CriticInput(
                snapshot_slug=snapshot_slug, files=files_spec, prompt_sha256=hash_and_upsert_prompt(prompt_text)
            ),
            client=build_client(model),
            content_root=wiring.working_dir,
            mount_properties=True,
            verbose=True,
        )

        # Output final message if requested
        if output_final_message:
            output_final_message.write_text(critic_output.result.model_dump_json(indent=2), encoding="utf-8")

        # Display results
        if not final_only:
            Console().print(render_to_rich(critic_output.result))
        return

    # Unstructured mode: manual setup with TranscriptHandler
    ts = format_timestamp_session()
    dest_root = Path(tempfile.gettempdir()) / "adgn_runs" / label / ts
    dest_root.mkdir(parents=True, exist_ok=True)

    async with Compositor() as comp:
        await wiring.attach(comp)
        handlers = [DisplayEventsHandler(max_lines=10), TranscriptHandler(events_path=dest_root / "events.jsonl")]
        print(f"[run] Transcript: {dest_root}")
        async with Client(comp) as mcp_client:
            agent = await MiniCodex.create(
                mcp_client=mcp_client,
                system="You are a code agent. Use tools to execute commands. Respond concisely.",
                client=build_client(model),
                handlers=handlers,
                parallel_tool_calls=True,
                tool_policy=RequireAnyTool(),
            )
            result = await agent.run(prompt_text)
            if output_final_message:
                output_final_message.write_text(result.text or "", encoding="utf-8")
            elif not final_only and (result.text or ""):
                print(result.text)


# --- Unified run command (structured/freeform; preset/prompt-file/text) ---

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
    # Scope (exactly one)
    path: Path | None = opt.OPT_RUNBOOK_PATH,
    snapshot: SnapshotSlug | None = opt.OPT_RUNBOOK_SNAPSHOT,
    # Prompt source (at most one; default by mode)
    preset: str | None = typer.Option(
        None, "--preset", help="Built-in prompt name; see 'adgn-properties list-presets'"
    ),
    prompt_file: Path | None = typer.Option(None, "--prompt-file", exists=True, dir_okay=False, readable=True),  # noqa: B008
    prompt_text: str | None = typer.Option(
        None, "--prompt-text", help="Inline prompt text (discouraged for long prompts)"
    ),
    # Mode
    structured: bool = typer.Option(False, help="Attach critic_submit and require structured submit flow"),
    # File filtering
    files: list[str] | None = opt.OPT_FILES_FILTER,
    # Common options
    model: str = opt.OPT_MODEL,
    final_only: bool = opt.OPT_FINAL_ONLY,
    output_final_message: Path | None = opt.OPT_OUTPUT_FINAL_MESSAGE,
    dry_run: bool = typer.Option(False, help="Compose prompt only; save to /tmp and exit"),
) -> None:
    """Unified runner: snapshot|path + structured|freeform + preset|prompt-file|text.

    Defaults:
    - structured=false: preset=open (if no prompt source provided)
    - structured=true: preset=max-recall-critic (if no prompt source provided)
    """
    # Initialize DB unconditionally (needed for snapshot file resolution, structured runs, etc.)
    init_db()

    # Validate scope
    if (path is None and snapshot is None) or (path is not None and snapshot is not None):
        print("ERROR: Provide exactly one of --path or --snapshot.")
        raise typer.Exit(2)
    # Validate prompt source
    sources = [x is not None for x in (preset, prompt_file, prompt_text)]
    if sum(sources) == 0:
        preset = "max-recall-critic" if structured else "open"
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

    # Validate --files only works with snapshots
    if files and path is not None:
        print("ERROR: --files only works with --snapshot, not --path.")
        raise typer.Exit(2)

    # Validate structured mode requires snapshot (for DB persistence)
    if structured and path is not None:
        print("ERROR: --structured requires --snapshot (not --path) for database persistence.")
        raise typer.Exit(2)

    # Create hydrator once at CLI entry point (always, even for path mode - lightweight)
    hydrator = SnapshotHydrator.from_package_resources()

    # Enter workspace context and run (same path for dry-run and real execution)
    async with _open_run_context(path, snapshot, files, hydrator) as (wiring, files_spec, label):
        # Resolve files for prompt rendering (snapshot mode resolves sentinel, path mode is already explicit)
        if snapshot is not None:
            resolved_files = await resolve_critic_scope(snapshot_slug=snapshot, files=files_spec)
        else:
            # Path mode: files_spec is already set[Path]
            resolved_files = files_spec  # type: ignore[assignment]

        prompt = _render_prompt_with_context(prompt_raw, wiring=wiring, files=resolved_files)
        await _exec_agent(
            wiring=wiring,
            prompt_text=prompt,
            model=model,
            structured=structured,
            output_final_message=output_final_message,
            final_only=final_only,
            label=label,
            snapshot_slug=snapshot,
            files_spec=files_spec if snapshot is not None else None,
            dry_run=dry_run,
        )


@app.command("list-presets")
def cmd_list_presets() -> None:
    """List available built-in prompt presets and their descriptions."""
    _print_presets()
