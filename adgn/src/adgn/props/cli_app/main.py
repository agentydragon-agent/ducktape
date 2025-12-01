"""Typer-based CLI entry for adgn-properties.

Incremental migration target: we will gradually move subcommands here.
Current scope: prompt-optimize (with --context) and prompt-eval will be added next.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import functools
from importlib import resources
import json
import logging
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import UUID

import docker
from fastmcp.client import Client
from rich.console import Console
from rich.traceback import install as rich_traceback_install
import typer

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.llm.logging_config import configure_logging
from adgn.llm.rendering.rich_renderers import render_to_rich

# in-proc servers are mounted via Compositor.mount_inproc
from adgn.mcp._shared.constants import SLEEP_FOREVER_CMD
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.cli_shared import (
    BuildOptions,
    build_cmd,
    detect_tools,
    hash_and_upsert_prompt,
    run_check_minicodex_async,
    save_prompt_to_tmp,
)
from adgn.props.cluster_unknowns import cluster_unknowns
from adgn.props.critic import ALL_FILES_WITH_ISSUES, CriticInput, FileScopeSpec, resolve_critic_scope, run_critic
from adgn.props.db import get_session, init_db, recreate_database
from adgn.props.db.models import GraderRun as DBGraderRun
from adgn.props.db.sync_specimens import ensure_specimens_synced, force_sync_specimens
from adgn.props.docker_env import (
    PROPERTIES_DOCKER_IMAGE,
    WORKING_DIR as CRITIC_WORKDIR,
    PropertiesDockerWiring,
    build_critic_volumes,
    ensure_critic_image,
    properties_docker_spec,
)
from adgn.props.eval_harness import run_all_evals
from adgn.props.grader import GraderOutput, grade_critique_by_id
from adgn.props.lint_issue import run_specimen_lint_issue_async
from adgn.props.models.issue import IssueCore, LineRange, Occurrence
from adgn.props.prompt_optimizer import run_prompt_optimizer
from adgn.props.prompts.builder import build_enforce_prompt
from adgn.props.prompts.schemas import build_input_schemas_json
from adgn.props.prompts.util import build_standard_context, enumerate_files_from_path, get_templates_env
from adgn.props.runs_context import RunsContext, format_timestamp_session
from adgn.props.specimens.registry import SpecimenRegistry

# Reduce Rich traceback verbosity for CLI errors
rich_traceback_install(show_locals=False, max_frames=12, extra_lines=1, width=100)

logger = logging.getLogger(__name__)


app = typer.Typer(help="adgn-properties (Typer) — properties tooling", add_completion=False)

# Typer parameter singletons to avoid function-call defaults in signatures (ruff B008)
ARG_WORKDIR = typer.Argument(..., exists=True, file_okay=False, resolve_path=True)
ARG_SCOPE = typer.Argument(..., help="Freeform scope description (e.g. 'all files under src/**')")
OPT_MODEL = typer.Option("gpt-5", help="Model id")
OPT_DRY_RUN = typer.Option(False, help="Compose prompt only; do not run")
OPT_FINAL_ONLY = typer.Option(False, help="Print only final message")
OPT_OUTPUT_FINAL_MESSAGE = typer.Option(None, help="Write final message to this path")
OPT_ALLOW_GENERAL = typer.Option(False, help="Allow general code-quality findings beyond formal properties")
# Additional shared Typer params (B008-safe)
ARG_SPECIMEN = typer.Argument(..., help="Specimen slug (under properties/specimens)")
ARG_ISSUE_ID = typer.Argument(..., help="Issue id to lint (must have should_flag=true)")
ARG_OCCURRENCE = typer.Argument(..., help="0-based occurrence index")
ARG_CMD_LIST = typer.Argument(..., help="Command to run inside container")
ARG_PROMPT = typer.Argument(..., help="Candidate critic system prompt to evaluate across specimens")
OPT_OUTPUT_DIR = typer.Option(None, help="Root directory for run artifacts")
OPT_CONTEXT = typer.Option(
    "minimal", help=("Agent context: minimal (no extra servers) or props (mount /props via docker MCP)")
)
OPT_CRITIQUE = typer.Option(..., "--critique", exists=True, help="Path to the input critique JSON file")
OPT_INTERACTIVE = typer.Option(False, "-i", help="Attach STDIN (docker exec -i)")
OPT_TTY_EXEC = typer.Option(False, "-t", help="Allocate TTY (docker exec -t)")
OPT_WORKDIR_CRITIC = typer.Option(CRITIC_WORKDIR, "--workdir", help="Container working dir (default: /workspace)")
# Shared option for iteration budget
OPT_MAX_ITERS = typer.Option(10, help="Maximum number of prompt evaluations (tool calls)")
OPT_SKIP_GIT_REPO_CHECK = typer.Option(False, help="Pass --skip-git-repo-check to codex exec")
OPT_FULL_AUTO = typer.Option(False, help="Pass --full-auto to codex exec")
OPT_FILES_FILTER = typer.Option(None, "--files", help="Limit review to specific files (relative paths)")


@app.callback()
def _init_logging() -> None:
    configure_logging()


@dataclass
class MetricsRow:
    iteration: int
    mean_recall: float
    tp: int
    fp: int
    fn: int
    unknown: int
    dir: str


def async_run(fn):
    """Decorator to run an async Typer command via asyncio.run (DRY)."""

    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return _wrapper


@app.command("check")
@async_run
async def cmd_check(
    workdir: Path = ARG_WORKDIR,
    scope: str = ARG_SCOPE,
    model: str = OPT_MODEL,
    dry_run: bool = OPT_DRY_RUN,
    final_only: bool = OPT_FINAL_ONLY,
    output_final_message: Path | None = OPT_OUTPUT_FINAL_MESSAGE,
    allow_general_findings: bool = OPT_ALLOW_GENERAL,
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


def _filter_files(all_files: Mapping[Path, object], requested_files: list[str] | None) -> FileScopeSpec:
    """Filter available files to requested subset, with validation.

    Args:
        all_files: All available files from specimen
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
        typer.echo("Error: The following files are not in the specimen:", err=True)
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


async def _run_specimen_minicodex_async(
    specimen: str,
    *,
    dry_run: bool,
    embed_paths: list[Path] | None,
    mode: str,
    final_only: bool,
    output_final_message: Path | None,
    client: OpenAIModelProto,
    files: list[str] | None = None,
    registry: SpecimenRegistry,
) -> int:
    # Load and hydrate specimen (single hydration for both dry-run and real run)
    async with registry.load_and_hydrate(specimen) as hydrated:
        supplemental_text = read_embedded_paths(embed_paths) if embed_paths else None

        # Filter files if requested (returns FileScopeSpec: sentinel or explicit set)
        files_spec = _filter_files(hydrated.all_discovered_files, files)

        # Resolve files for prompt rendering
        resolved_files = await resolve_critic_scope(specimen_slug=specimen, files=files_spec)

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
            prompt_file = tmpdir / f"codex_prompt_specimen_{mode}.md"
            prompt_file.write_text(prompt, encoding="utf-8")
            typer.echo(f"Prompt saved to: {prompt_file}")
            return 0

        # Use run_critic for structured execution and DB persistence
        critic_output, _critic_run_id, _critique_id = await run_critic(
            input_data=CriticInput(
                specimen_slug=specimen, files=files_spec, prompt_sha256=hash_and_upsert_prompt(prompt)
            ),
            client=client,
            system_prompt="You are a code agent. Be concise.",
            user_prompt=prompt,
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


# specimen-check command removed in favor of the unified 'run' command.


@app.command("specimen-discover")
@async_run
async def cmd_specimen_discover(
    specimen: str = ARG_SPECIMEN,
    dry_run: bool = OPT_DRY_RUN,
    final_only: bool = OPT_FINAL_ONLY,
    output_final_message: Path | None = OPT_OUTPUT_FINAL_MESSAGE,
    files: list[str] | None = OPT_FILES_FILTER,
) -> None:
    """Discover only-new issues vs specimen notes (covered/not_covered_yet)."""
    registry = SpecimenRegistry.from_package_resources()
    # Build full specimen list
    names = registry.list_specimen_names()
    if specimen not in names:
        typer.echo(f"Unknown specimen slug: {specimen}\nAvailable: \n" + "\n".join(f" - {n}" for n in names))
        raise typer.Exit(2)
    # TODO: Remove this manual path wrangling. The covered.md/not_covered_yet.md files
    # should be deprecated and removed, along with specimen-discover command and related paths.
    spec_dir = registry.base_path / specimen
    embed_paths: list[Path] | None = [
        p for p in [spec_dir / "covered.md", spec_dir / "not_covered_yet.md"] if p.exists()
    ]
    if not embed_paths:
        embed_paths = None
    rc = await _run_specimen_minicodex_async(
        specimen,
        dry_run=dry_run,
        embed_paths=embed_paths,
        mode="discover",
        final_only=final_only,
        output_final_message=output_final_message,
        client=build_client("gpt-5"),
        files=files,
        registry=registry,
    )
    raise typer.Exit(code=rc)


@app.command("cluster-unknowns")
@async_run
async def cmd_cluster_unknowns(model: str = OPT_MODEL, out_dir: Path | None = OPT_OUTPUT_DIR) -> None:
    """Cluster all 'unknown' issues across all prompt_optimize runs via an in-proc MCP tool.

    The agent must submit a single payload of clusters: [{name: str, issues: [uid,...]}].
    """
    init_db()
    root = await cluster_unknowns(model=model, out_dir=out_dir, ctx=RunsContext.from_pkg_dir())
    typer.echo(f"Clusters written to: {root}/<specimen>/clusters.json")


@app.command("prompt-optimize")
@async_run
async def prompt_optimize(
    budget: float = typer.Option(50.0, "--budget", help="$ budget for optimization"),
    model: str = OPT_MODEL,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output with agent progress display"),
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt using prompt_eval MCP with $ budget."""
    init_db()
    await run_prompt_optimizer(budget=budget, ctx=RunsContext.from_pkg_dir(), model=model, verbose=verbose)


@app.command("prompt-eval")
@async_run
async def prompt_eval(
    prompt: str = typer.Argument(..., help="Candidate critic system prompt to evaluate across specimens"),
    out_dir: Path | None = OPT_OUTPUT_DIR,
    model: str = OPT_MODEL,
    debug: bool = typer.Option(False, help="Log raw OpenAI HTTP to JSONL for diagnostics"),
) -> None:
    """Evaluate a critic system prompt across all known specimens and emit metrics list.

    DEPRECATED: This command is being replaced by the database-backed workflow.
    Use the prompt_eval MCP server or database queries instead.
    """
    typer.echo("Error: prompt-eval command is deprecated", err=True)
    typer.echo("", err=True)
    typer.echo("The prompt-eval workflow has been migrated to database-backed runs.", err=True)
    typer.echo("Use one of these alternatives:", err=True)
    typer.echo("  1. prompt_eval MCP server: run_critic(specimen, files, prompt_text, model)", err=True)
    typer.echo("  2. Database queries: Query critic_runs and grader_runs tables", err=True)
    typer.echo("  3. CLI: adgn-properties2 run --specimen <slug> --structured true --prompt-text '<prompt>'", err=True)
    raise typer.Exit(1)


@app.command("specimen-grade")
@async_run
async def specimen_grade(
    critique_id: str = typer.Argument(..., help="Critique ID (UUID) from database"), model: str = OPT_MODEL
) -> None:
    """Grade a critique by database ID against canonical findings.

    Fetches critique from database, executes grader, and persists results.
    """
    init_db()

    grader_run_id = await grade_critique_by_id(UUID(critique_id), build_client(model))

    # Query database for the grader run
    with get_session() as session:
        db_grader_run = session.get(DBGraderRun, grader_run_id)
        if db_grader_run is None:
            raise RuntimeError(f"Grader run {grader_run_id} not found in database")

        # Parse and display output
        output = GraderOutput.model_validate(db_grader_run.output)

        typer.echo(f"Graded critique {critique_id}")
        typer.echo(f"Grader run ID: {grader_run_id}")
        typer.echo(f"Grader run transcript_id: {db_grader_run.transcript_id}")
        typer.echo(f"Specimen: {db_grader_run.specimen_slug}")
        typer.echo("")
        typer.echo(output.model_dump_json(indent=2))


@app.command("fix")
def cmd_fix(
    workdir: Path = ARG_WORKDIR,
    scope: str = typer.Argument(..., help="Freeform scope description to enforce"),
    model: str = OPT_MODEL,
    final_only: bool = OPT_FINAL_ONLY,
    output_final_message: Path | None = OPT_OUTPUT_FINAL_MESSAGE,
    skip_git_repo_check: bool = OPT_SKIP_GIT_REPO_CHECK,
    full_auto: bool = OPT_FULL_AUTO,
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
    specimen: str = typer.Argument(..., help="Specimen slug (under properties/specimens)"),
    issue_id: str = typer.Argument(..., help="Issue id to lint (must have should_flag=true)"),
    occurrence: int = typer.Argument(..., help="0-based occurrence index"),
    model: str = OPT_MODEL,
    dry_run: bool = OPT_DRY_RUN,
) -> None:
    rc = await run_specimen_lint_issue_async(
        specimen, issue_id, model=model, dry_run=dry_run, occurrence_index=occurrence, client=build_client(model)
    )
    raise typer.Exit(code=rc)


@app.command("eval-all")
@async_run
async def cmd_eval_all() -> None:
    await run_all_evals(client=build_client("gpt-5"), ctx=RunsContext.from_pkg_dir())


@app.command("sync-specimens")
@async_run
async def cmd_sync_specimens(force: bool = typer.Option(False, "--force", help="Force re-sync (clear cache)")) -> None:
    """Sync specimens table from splits.py (train/valid/test assignments).

    Auto-sync happens on first DB operation per process. Use this for:
    - Manual sync after editing splits.py
    - Forcing re-sync with --force flag

    Requires PROPS_DB_URL environment variable (admin credentials).
    """
    init_db()

    if force:
        typer.echo("Force re-syncing specimens table...")
        stats = await force_sync_specimens()
    else:
        typer.echo("Syncing specimens table...")
        stats = await ensure_specimens_synced()

    typer.echo(
        f"Sync complete: {stats['total']} specimens "
        f"(+{stats['added']} added, ~{stats['updated']} updated, -{stats['deleted']} deleted)"
    )


@app.command("db-recreate")
@async_run
async def cmd_db_recreate(yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")) -> None:
    """Recreate database from scratch (destructive - drops all tables/views/policies).

    This command will:
    1. Drop all existing tables, views, and RLS policies
    2. Create agent_user role (read-only with RLS)
    3. Create tables from ORM models
    4. Enable Row-Level Security policies
    5. Sync specimens from splits.py

    Requires PROPS_DB_URL environment variable (postgres superuser connection).
    """
    if not yes:
        typer.echo("⚠️  WARNING: This will DELETE ALL data in the database!")
        confirm = typer.prompt("Type 'yes' to confirm")
        if confirm != "yes":
            typer.echo("Aborted")
            raise typer.Exit(1)

    # Connect and recreate
    init_db()
    recreate_database()

    # Sync specimens
    typer.echo("Syncing specimens...")
    stats = await ensure_specimens_synced()
    typer.echo(f"✓ Database recreated with {stats['total']} specimens")


OPT_RUNBOOK_PATH = typer.Option(
    None,
    "--path",
    exists=True,
    file_okay=False,
    resolve_path=True,
    help="Local code path to mount as /workspace (read-only)",
)
OPT_RUNBOOK_SPECIMEN = typer.Option(
    None, "--specimen", help="Specimen slug to hydrate and mount as /workspace (read-only)"
)


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
    context = build_standard_context(
        files=files, wiring=wiring, available_tools=detect_tools(), supplemental_text=supplemental_text
    )
    return str(tmpl.render(**context))


@asynccontextmanager
async def _open_run_context(
    path: Path | None, specimen: str | None, files: list[str] | None, registry: SpecimenRegistry
):
    """Yield (wiring, files_spec, label) for either a local path or a hydrated specimen.

    Args:
        path: Local directory path (mutually exclusive with specimen)
        specimen: Specimen slug (mutually exclusive with path)
        files: Optional file filter (only for specimens)
        registry: SpecimenRegistry instance (always required, instantiated at CLI entry point)

    Yields:
        (wiring, files_spec, label) tuple where files_spec is FileScopeSpec
    """
    if path is not None:
        wiring = properties_docker_spec(path, mount_properties=True, ephemeral=False)
        all_files = enumerate_files_from_path(path)
        yield wiring, all_files, path.name
        return
    # Load and hydrate specimen (single hydration, avoid wasteful re-hydrate)
    async with registry.load_and_hydrate(specimen or "") as hydrated:
        wiring = properties_docker_spec(hydrated.content_root, mount_properties=True, ephemeral=False)
        files_spec = _filter_files(hydrated.all_discovered_files, files)
        yield wiring, files_spec, hydrated.slug


async def _exec_agent(
    *,
    wiring: PropertiesDockerWiring,
    prompt_text: str,
    model: str,
    structured: bool,
    output_final_message: Path | None,
    final_only: bool,
    label: str,
    specimen_slug: str | None,
    files_spec: FileScopeSpec | None,
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
        assert specimen_slug is not None, "structured mode requires specimen_slug"
        assert files_spec is not None, "structured mode requires files_spec"
        critic_output, _critic_run_id, _critique_id = await run_critic(
            input_data=CriticInput(
                specimen_slug=specimen_slug, files=files_spec, prompt_sha256=hash_and_upsert_prompt(prompt_text)
            ),
            client=build_client(model),
            system_prompt="You are a code agent. Use tools to execute commands. Respond concisely.",
            user_prompt=prompt_text,
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

    comp = Compositor("compositor")
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
    # Detectors/runbooks
    "dead-code-and-reachability": "detectors/prompts/dead_code_and_reachability.j2.md",
    "flag-propagation": "detectors/prompts/flag_propagation.j2.md",
    "contract-truthfulness": "detectors/prompts/contract_truthfulness.j2.md",
}


def _print_presets() -> None:
    for name in sorted(_PRESET_MAP.keys()):
        print(name)


def _load_preset_text(name: str) -> str:
    if not (rel := _PRESET_MAP.get(name)):
        raise typer.BadParameter(f"Unknown preset: {name}. Use --list-presets to see options.")
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
    path: Path | None = OPT_RUNBOOK_PATH,
    specimen: str | None = OPT_RUNBOOK_SPECIMEN,
    # Prompt source (at most one; default by mode)
    preset: str | None = typer.Option(None, "--preset", help="Built-in prompt name; see --list-presets"),
    prompt_file: Path | None = typer.Option(None, "--prompt-file", exists=True, dir_okay=False, readable=True),  # noqa: B008
    prompt_text: str | None = typer.Option(
        None, "--prompt-text", help="Inline prompt text (discouraged for long prompts)"
    ),
    # Mode
    structured: bool = typer.Option(False, help="Attach critic_submit and require structured submit flow"),
    # File filtering
    files: list[str] | None = OPT_FILES_FILTER,
    # Common options
    model: str = OPT_MODEL,
    final_only: bool = OPT_FINAL_ONLY,
    output_final_message: Path | None = OPT_OUTPUT_FINAL_MESSAGE,
    list_presets: bool = typer.Option(False, "--list-presets", help="List available built-in presets and exit"),
    dry_run: bool = typer.Option(False, help="Compose prompt only; save to /tmp and exit"),
) -> None:
    """Unified runner: specimen|path + structured|freeform + preset|prompt-file|text.

    Defaults:
    - structured=false: preset=open (if no prompt source provided)
    - structured=true: preset=max-recall-critic (if no prompt source provided)
    """
    if list_presets:
        _print_presets()
        return

    # Initialize DB for structured runs (calls run_critic/run_grader)
    if structured:
        init_db()

    # Validate scope
    if (path is None and specimen is None) or (path is not None and specimen is not None):
        print("ERROR: Provide exactly one of --path or --specimen.")
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

    # Validate --files only works with specimens
    if files and path is not None:
        print("ERROR: --files only works with --specimen, not --path.")
        raise typer.Exit(2)

    # Validate structured mode requires specimen (for DB persistence)
    if structured and path is not None:
        print("ERROR: --structured requires --specimen (not --path) for database persistence.")
        raise typer.Exit(2)

    # Create registry once at CLI entry point (always, even for path mode - lightweight)
    registry = SpecimenRegistry.from_package_resources()

    # Enter workspace context and run (same path for dry-run and real execution)
    async with _open_run_context(path, specimen, files, registry) as (wiring, files_spec, label):
        # Resolve files for prompt rendering (specimen mode resolves sentinel, path mode is already explicit)
        if specimen is not None:
            resolved_files = await resolve_critic_scope(specimen_slug=specimen, files=files_spec)
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
            specimen_slug=specimen,
            files_spec=files_spec if specimen is not None else None,
            dry_run=dry_run,
        )


@app.command("list-presets")
def cmd_list_presets() -> None:
    """List available built-in prompt presets and their descriptions."""
    _print_presets()


@app.command("specimen-dump")
@async_run
async def specimen_dump(
    specimen: str = typer.Argument(..., help="Specimen slug to dump as JSON"),
    pretty: bool = typer.Option(True, help="Pretty-print JSON with indentation"),
) -> None:
    """Dump a specimen's full structure as JSON (manifest, all issues, occurrences)."""
    registry = SpecimenRegistry.from_package_resources()
    try:
        async with registry.load_and_hydrate(specimen) as hydrated:
            rec = hydrated.record

            # Use existing Pydantic model_dump() for all structured data
            output = {
                "slug": rec.slug,
                "manifest": rec.manifest.model_dump(mode="json"),
                "issues": {
                    issue_id: {
                        "core": issue.core.model_dump(mode="json"),
                        "instances": [occ.model_dump(mode="json") for occ in issue.instances],
                    }
                    for issue_id, issue in rec.issues.items()
                },
                "false_positives": {
                    issue_id: {
                        "core": issue.core.model_dump(mode="json"),
                        "instances": [occ.model_dump(mode="json") for occ in issue.instances],
                    }
                    for issue_id, issue in rec.false_positives.items()
                },
            }

            indent = 2 if pretty else None
            print(json.dumps(output, indent=indent))
    except Exception as e:
        typer.echo(f"ERROR: Failed to load specimen '{specimen}': {e}")
        raise typer.Exit(2) from e


@app.command("specimen-exec")
@async_run
async def specimen_exec(
    specimen: str = typer.Argument(..., help="Specimen name/path or manifest"),
    workdir: Path = OPT_WORKDIR_CRITIC,
    interactive: bool = OPT_INTERACTIVE,
    tty_exec: bool = OPT_TTY_EXEC,
    cmd: list[str] = ARG_CMD_LIST,
) -> None:
    """Execute a command in a container with hydrated specimen mounted at /workspace (RW)."""
    # Docker sanity
    try:
        dclient = docker.from_env()
        dclient.ping()
    except Exception as e:
        typer.echo(f"ERROR: Docker daemon not reachable: {e}")
        raise typer.Exit(2) from e
    ensure_critic_image()

    # Load and hydrate specimen (keep hydrated for entire container lifetime)
    registry = SpecimenRegistry.from_package_resources()
    async with registry.load_and_hydrate(specimen) as hydrated:
        try:
            _ = next(hydrated.content_root.iterdir())
        except StopIteration:
            typer.echo(f"ERROR: hydrated specimen is empty: {hydrated.content_root}")
            raise typer.Exit(2) from None
        name = f"adgn_spec_shell_{int(time.time())}"
        volumes, _defs = build_critic_volumes(hydrated.content_root, mount_properties=True, workspace_mode="rw")
        container = dclient.containers.run(
            image=PROPERTIES_DOCKER_IMAGE,
            command=SLEEP_FOREVER_CMD,
            name=name,
            remove=True,
            detach=True,
            network_mode="none",
            volumes=volumes,
            working_dir=str(workdir),
            tty=True,
            stdin_open=True,
        )
        try:
            exec_cmd = ["docker", "exec"]
            if interactive:
                exec_cmd.append("-i")
            if tty_exec:
                exec_cmd.append("-t")
            exec_cmd.append(name)
            exec_cmd.extend(cmd)
            proc = await asyncio.create_subprocess_exec(*exec_cmd)
            rc = await proc.wait()
            raise typer.Exit(rc)
        finally:
            container.stop()
