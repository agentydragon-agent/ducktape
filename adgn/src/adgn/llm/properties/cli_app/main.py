"""Typer-based CLI entry for adgn-properties.

Incremental migration target: we will gradually move subcommands here.
Current scope: prompt-optimize (with --context) and prompt-eval will be added next.
"""

from __future__ import annotations

import asyncio
import csv
from dataclasses import asdict, dataclass
from datetime import datetime
import functools
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Literal

import docker
import matplotlib
import matplotlib.pyplot as plt
from openai import AsyncOpenAI
from rich.console import Console
import tiktoken
import typer

from adgn.llm.logging_config import configure_logging
from adgn.llm.mcp._shared.constants import SLEEP_FOREVER_CMD
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import GateUntil
from adgn.llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mini_codex.transcript_handler import TranscriptHandler
from adgn.llm.properties.cli import (
    BuildOptions,
    _detect_tools,
    _run_check_minicodex_async,
    build_cmd,
)
from adgn.llm.properties.cluster_unknowns import cluster_unknowns
from adgn.llm.properties.critic import (
    CriticSubmitPayload,
    CriticSubmitState,
    make_critic_submit_server,
)
from adgn.llm.properties.docker_env import (
    PROPERTIES_DOCKER_IMAGE,
    WORKING_DIR as CRITIC_WORKDIR,
    PropertiesDockerWiring,
    build_critic_volumes,
    ensure_critic_image,
    properties_docker_spec,
)
from adgn.llm.properties.eval_harness import run_all_evals
from adgn.llm.properties.grade_runner import _metrics_row, grade_critic_output
from adgn.llm.properties.lint_issue import run_specimen_lint_issue_async
from adgn.llm.properties.models.issue import IssueCore, LineRange, Occurrence
from adgn.llm.properties.prompt_eval.server import (
    _run_critic_for_specimen,
    build_server as build_prompt_eval_server,
)
from adgn.llm.properties.prompts.builder import (
    build_check_prompt,
    build_enforce_prompt,
    build_input_schemas_json,
    build_role_prompt,
)
from adgn.llm.properties.prompts.util import build_scope_text
from adgn.llm.properties.prop_utils import pkg_dir
from adgn.llm.properties.specimens.registry import (
    SpecimenRegistry,
    find_specimens_base,
    list_specimen_names,
)
from adgn.llm.rendering.rich_renderers import render_to_rich

app = typer.Typer(
    help="adgn-properties (Typer) — properties tooling", add_completion=False
)

# Typer parameter singletons to avoid function-call defaults in signatures (ruff B008)
ARG_WORKDIR = typer.Argument(..., exists=True, file_okay=False, resolve_path=True)
ARG_SCOPE = typer.Argument(
    ...,
    help="Freeform scope description (e.g. 'all files under src/**')",
)
OPT_MODEL = typer.Option("gpt-5", help="Model id")
OPT_DRY_RUN = typer.Option(False, help="Compose prompt only; do not run")
OPT_FINAL_ONLY = typer.Option(False, help="Print only final message")
OPT_OUTPUT_FINAL_MESSAGE = typer.Option(
    None,
    help="Write final message to this path",
)
OPT_ALLOW_GENERAL = typer.Option(
    False,
    help="Allow general code-quality findings beyond formal properties",
)
# Additional shared Typer params (B008-safe)
ARG_SPECIMEN = typer.Argument(
    ...,
    help="Specimen slug (under properties/specimens)",
)
ARG_ISSUE_ID = typer.Argument(
    ...,
    help="Issue id to lint (must have should_flag=true)",
)
ARG_OCCURRENCE = typer.Argument(..., help="0-based occurrence index")
ARG_CMD_LIST = typer.Argument(..., help="Command to run inside container")
ARG_PROMPT = typer.Argument(
    ...,
    help="Candidate critic system prompt to evaluate across specimens",
)
OPT_GITCONFIG = typer.Option(
    None,
    help="Path to a gitconfig for private repo fallback",
)
OPT_OUTPUT_DIR = typer.Option(
    None,
    help="Root directory for run artifacts",
)
OPT_CONTEXT = typer.Option(
    "minimal",
    help=(
        "Agent context: minimal (no extra servers) or props (mount /props via docker MCP)"
    ),
)
OPT_CRITIQUE = typer.Option(
    ...,
    "--critique",
    exists=True,
    help="Path to the input critique JSON file",
)
OPT_INTERACTIVE = typer.Option(False, "-i", help="Attach STDIN (docker exec -i)")
OPT_TTY_EXEC = typer.Option(False, "-t", help="Allocate TTY (docker exec -t)")
OPT_WORKDIR_CRITIC = typer.Option(
    CRITIC_WORKDIR,
    "--workdir",
    help="Container working dir (default: /workspace)",
)
# Shared option for iteration budget
OPT_MAX_ITERS = typer.Option(
    10, help="Maximum number of prompt evaluations (tool calls)"
)
OPT_SKIP_GIT_REPO_CHECK = typer.Option(
    False,
    help="Pass --skip-git-repo-check to codex exec",
)
OPT_FULL_AUTO = typer.Option(False, help="Pass --full-auto to codex exec")


def _resolve_gitconfig(arg_val: str | None) -> Path | None:
    """Resolve --gitconfig consistently.

    - If provided: expanduser/resolve and require that it exists (exit 2 on missing)
    - Else: fallback to pkg_dir()/gitconfig.local if present
    - Else: return None
    """
    if arg_val:
        p = Path(arg_val).expanduser().resolve()
        if not p.exists():
            print(f"ERROR: --gitconfig file not found: {p}")
            raise SystemExit(2)
        return p
    cfg = pkg_dir() / "gitconfig.local"
    return cfg if cfg.exists() else None


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

    # Dry-run path: compose prompt only and save it to a temp file (compat with legacy tests)
    if dry_run:
        # Compose prompt without spinning up docker/agent
        wiring = PropertiesDockerWiring(
            server_spec=None,  # type: ignore[arg-type]
            working_dir=Path("/"),
            definitions_container_dir=None,
            image_name="n/a",
        )
        prompt_text = build_check_prompt(
            scope,
            wiring=wiring,
            allow_general_findings=allow_general_findings,
        )
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        outfile = tmpdir / f"codex_prompt_check_{ts}.md"
        outfile.write_text(prompt_text, encoding="utf-8")
        tokens = len(tiktoken.get_encoding("cl100k_base").encode(prompt_text))
        typer.echo(f"Saved prompt: {outfile} (approx tokens: {tokens})")
        return

    wiring = properties_docker_spec(workdir, mount_properties=True)
    role_mode: Literal["find", "open", "discover"] = (
        "open" if allow_general_findings else "find"
    )
    prompt_text = build_role_prompt(
        role_mode,
        scope,
        wiring=wiring,
        supplemental_text=None,
        available_tools=_detect_tools(),
    )
    rc = await _run_check_minicodex_async(
        workdir,
        prompt_text,
        model=model,
        output_final_message=output_final_message,
        final_only=final_only,
        client=AsyncOpenAI(),
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


async def _run_specimen_minicodex_async(
    specimen: str,
    *,
    dry_run: bool,
    embed_paths: list[str] | None,
    gitconfig: Path | None,
    mode: str,
    final_only: bool,
    output_final_message: Path | None,
    client: AsyncOpenAI,
) -> int:
    rec = SpecimenRegistry.load_strict(specimen)
    man = rec.manifest

    supplemental_text = (
        read_embedded_paths([Path(p) for p in (embed_paths or [])])
        if embed_paths
        else None
    )

    # Build prompt according to mode
    scope_text = build_scope_text(man.scope.include, man.scope.exclude)
    role_mode: Literal["discover", "open", "find"] = (
        "discover" if mode == "discover" else ("open" if mode == "open" else "find")
    )

    # In dry-run, avoid hydration and Docker wiring; compose prompt only
    if dry_run:
        wiring = PropertiesDockerWiring(
            server_spec=None,  # type: ignore[arg-type]
            working_dir=Path("/"),
            definitions_container_dir=None,
            image_name="n/a",
        )
        prompt = build_role_prompt(
            role_mode,
            scope_text,
            wiring=wiring,
            supplemental_text=supplemental_text,
            available_tools=_detect_tools(),
        )
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        outfile = tmpdir / f"codex_prompt_specimen_{mode}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        tokens = len(tiktoken.get_encoding("cl100k_base").encode(prompt))
        print(f"Saved prompt: {outfile} (approx tokens: {tokens})")
        return 0

    async with rec.hydrated_copy(gitconfig) as content_root:
        wiring = properties_docker_spec(content_root, mount_properties=True)
        prompt = build_role_prompt(
            role_mode,
            scope_text,
            wiring=wiring,
            supplemental_text=supplemental_text,
            available_tools=_detect_tools(),
        )

        # Critic flow via MiniCodex: agent must call critic_submit.submit_result
        submit_state = CriticSubmitState()
        critic_server = make_critic_submit_server(submit_state, name="critic_submit")
        specs = {
            wiring.server_name: wiring.server_spec,
            "critic_submit": make_inproc_slot_spec(critic_server),
        }
        async with McpManager(specs) as mcp:
            agent = await MiniCodex.create(
                model="gpt-5",
                mcp=mcp,
                system="You are a code agent. Be concise.",
                client=client,
                handlers=[
                    GateUntil(
                        lambda: (submit_state.result is not None)
                        or (submit_state.error is not None),
                    ),
                    DisplayEventsHandler(max_lines=10),
                ],
                parallel_tool_calls=True,
            )
            result = await agent.run(prompt)
            if output_final_message:
                Path(output_final_message).write_text(
                    result.text or "",
                    encoding="utf-8",
                )
            if not final_only and (result.text or ""):
                print(result.text)
        # Allow either a successful result or an explicit error
        if submit_state.error is not None:
            Console().print(render_to_rich(submit_state.error))
            return 2
        assert submit_state.result is not None, (
            "Critic did not call submit_result or submit_error?"
        )
        Console().print(render_to_rich(submit_state.result))
        # Write critique JSON for specimen-check runs (find/open modes)
        if mode in ("find", "open"):
            ts = int(time.time())
            out_dir = Path.cwd() / "runs" / "specimen-check" / f"{specimen}_{ts}"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "critique.json"
            obj = submit_state.result
            s = obj.model_dump_json(indent=2)  # type: ignore[attr-defined]
            out_path.write_text(s, encoding="utf-8")
            print(f"Saved critique JSON: {out_path}")
        return 0


@app.command("specimen-check")
@async_run
async def cmd_specimen_check(
    specimen: str = ARG_SPECIMEN,
    dry_run: bool = OPT_DRY_RUN,
    final_only: bool = OPT_FINAL_ONLY,
    output_final_message: Path | None = OPT_OUTPUT_FINAL_MESSAGE,
    gitconfig: Path | None = OPT_GITCONFIG,
    allow_general_findings: bool = OPT_ALLOW_GENERAL,
) -> None:
    """Run a property scan on a saved specimen (uses manifest.yaml)."""
    base = find_specimens_base()
    names = list_specimen_names(base)
    if specimen not in names:
        typer.echo(
            f"Unknown specimen slug: {specimen}\nAvailable: \n"
            + "\n".join(f" - {n}" for n in names),
        )
        raise typer.Exit(2)

    git_path = _resolve_gitconfig(str(gitconfig) if gitconfig else None)
    mode: Literal["discover", "open", "find"] = (
        "open" if allow_general_findings else "find"
    )

    rc = await _run_specimen_minicodex_async(
        specimen,
        dry_run=dry_run,
        embed_paths=None,
        gitconfig=git_path,
        mode=mode,
        final_only=final_only,
        output_final_message=output_final_message,
        client=AsyncOpenAI(),
    )
    raise typer.Exit(code=rc)


@app.command("specimen-discover")
@async_run
async def cmd_specimen_discover(
    specimen: str = ARG_SPECIMEN,
    dry_run: bool = OPT_DRY_RUN,
    final_only: bool = OPT_FINAL_ONLY,
    output_final_message: Path | None = OPT_OUTPUT_FINAL_MESSAGE,
    gitconfig: Path | None = OPT_GITCONFIG,
) -> None:
    """Discover only-new issues vs specimen notes (covered/not_covered_yet)."""
    base = find_specimens_base()
    names = list_specimen_names(base)
    if specimen not in names:
        typer.echo(
            f"Unknown specimen slug: {specimen}\nAvailable: \n"
            + "\n".join(f" - {n}" for n in names),
        )
        raise typer.Exit(2)
    spec_dir = base / specimen
    embed_paths = [
        str(p)
        for p in [spec_dir / "covered.md", spec_dir / "not_covered_yet.md"]
        if p.exists()
    ]
    git_path = _resolve_gitconfig(str(gitconfig) if gitconfig else None)
    rc = await _run_specimen_minicodex_async(
        specimen,
        dry_run=dry_run,
        embed_paths=embed_paths,
        gitconfig=git_path,
        mode="discover",
        final_only=final_only,
        output_final_message=output_final_message,
        client=AsyncOpenAI(),
    )
    raise typer.Exit(code=rc)


@app.command("cluster-unknowns")
def cmd_cluster_unknowns(
    model: str = OPT_MODEL,
    out_dir: Path | None = OPT_OUTPUT_DIR,
) -> None:
    """Cluster all 'unknown' issues across all prompt_optimize runs via an in-proc MCP tool.

    The agent must submit a single payload of clusters: [{name: str, issues: [uid,...]}].
    """
    root = cluster_unknowns(model=model, out_dir=out_dir)
    typer.echo(f"Clusters written to: {root / 'clusters.json'}")


@app.command("prompt-optimize")
@async_run
async def prompt_optimize(
    max_iters: int = OPT_MAX_ITERS,
    out_dir: Path | None = OPT_OUTPUT_DIR,
    context: str = OPT_CONTEXT,
    model: str = OPT_MODEL,
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt using prompt_eval MCP."""
    # Build base specs with prompt_eval MCP
    pe_server, pe_state = build_prompt_eval_server(
        agent_model=model,
        client=AsyncOpenAI(),
    )
    specs = {"prompt_eval": make_inproc_slot_spec(pe_server)}

    system = (
        "You are an expert LLM prompt engineer.\n\n"
        "You can evaluate performance of a given prompt using prompt_eval.test_prompt(prompt: str).\n\n"
        "You will have a given maximum budget of prompt_eval.test_prompt calls. Wisely trade off exploration and exploitation."
    )

    # Optional docker MCP with /props mounted
    props_dir = None
    if context == "props":
        wiring = properties_docker_spec(pkg_dir(), mount_properties=True)
        specs["docker"] = wiring.server_spec
        props_dir = wiring.definitions_container_dir

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = (
        out_dir
        if out_dir is not None
        else (pkg_dir() / "runs" / "prompt_optimize" / ts)
    )
    root.mkdir(parents=True, exist_ok=True)

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system=system,
            client=AsyncOpenAI(),
            handlers=[
                TranscriptHandler(dest_dir=root / "prompt_optimize"),
                DisplayEventsHandler(max_lines=10),
                # TODO(mpokorny): This gate can be exceeded under parallel_tool_calls if
                # multiple prompt_eval.test_prompt calls are in-flight when the budget flips.
                # Consider moving budget enforcement into the server or serialize near limit.
                GateUntil(lambda: pe_state.successful_calls >= max_iters),
            ],
            parallel_tool_calls=True,
        )

        # Agent user message (kept simple and delegated to the system prompt)
        user = (
            f"Your budget is: {max_iters} prompt_eval.test_prompt calls.\n\n"
            "Iterate to find an optimal prompt for a code reviewer/critic LLM agent. "
            "Your priorities are: recall first, then precision."
            "\n\n"
            "Your prompt will run in a harness that ensures the critic follows the required downstream format. "
            "Do not prescribe output JSON schemas explicitly."
        )
        if props_dir:
            user += (
                "\n\nYou also have a docker MCP server 'docker'."
                f"\n\nRead content at {props_dir} to find some *nonexhaustive* examples of properties of good code critics should enforce. "
                "Note that these are only some specific formal examples that we captured formally - many issues we want to catch are not covered yet by any of these formal properties."
                "\n\nThe critic agent will run on the same Docker image as you have available."
            )
        res = await agent.run(user)
        (root / "final.md").write_text(getattr(res, "text", ""), encoding="utf-8")
        # Generate summary plots (mean recall and counts) across iterations

        matplotlib.use("Agg")

        # Discover iteration directories (numeric or round_*)
        iter_dirs = [
            p
            for p in root.iterdir()
            if p.is_dir() and (p.name.isdigit() or p.name.startswith("round_"))
        ]
        rows: list[MetricsRow] = []
        for d in iter_dirs:
            res_path = d / "results.json"
            if not res_path.exists():
                continue
            data = json.loads(res_path.read_text(encoding="utf-8"))
            m = re.search(r"(\d+)$", d.name)
            it = int(m.group(1)) if m else 0
            sum_tp = sum(int(x.get("true_positives", 0) or 0) for x in data)
            sum_fp = sum(int(x.get("false_positive", 0) or 0) for x in data)
            sum_fn = sum(int(x.get("false_negatives", 0) or 0) for x in data)
            sum_unk = sum(int(x.get("unknown", 0) or 0) for x in data)
            recs = []
            for x in data:
                val = (
                    x.get("fuzzy_recall")
                    if x.get("fuzzy_recall") is not None
                    else x.get("recall")
                )
                if isinstance(val, int | float):
                    recs.append(float(val))
            mean_recall = (sum(recs) / len(recs)) if recs else 0.0
            rows.append(
                MetricsRow(
                    iteration=it,
                    mean_recall=mean_recall,
                    tp=sum_tp,
                    fp=sum_fp,
                    fn=sum_fn,
                    unknown=sum_unk,
                    dir=d.name,
                ),
            )
        if rows:
            rows.sort(key=lambda r: r.iteration)
            # CSV
            csv_path = root / "recall_and_counts_by_iter.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "iteration",
                        "mean_recall",
                        "tp",
                        "fp",
                        "fn",
                        "unknown",
                        "dir",
                    ],
                )
                w.writeheader()
                for r in rows:
                    w.writerow(asdict(r))
            # Plot
            xs = [r.iteration for r in rows]
            fig, axes = plt.subplots(2, 3, figsize=(10, 6), constrained_layout=True)
            (ax_rec, ax_tp, ax_fp), (ax_fn, ax_unk, ax_empty) = axes
            ax_rec.plot(xs, [r.mean_recall for r in rows], marker="o")
            ax_rec.set_title("Mean recall")
            ax_rec.grid(True, alpha=0.3)
            ax_tp.plot(xs, [r.tp for r in rows], marker="o", color="#2ca02c")
            ax_tp.set_title("True positives (sum)")
            ax_tp.grid(True, alpha=0.3)
            ax_fp.plot(xs, [r.fp for r in rows], marker="o", color="#d62728")
            ax_fp.set_title("False positives (sum)")
            ax_fp.grid(True, alpha=0.3)
            ax_fn.plot(xs, [r.fn for r in rows], marker="o", color="#9467bd")
            ax_fn.set_title("Positives missed (FN sum)")
            ax_fn.grid(True, alpha=0.3)
            ax_unk.plot(xs, [r.unknown for r in rows], marker="o", color="#8c564b")
            ax_unk.set_title("Unknown (sum)")
            ax_unk.grid(True, alpha=0.3)
            ax_empty.axis("off")
            fig.suptitle("Prompt optimize: recall and counts by iteration", fontsize=12)
            fig.savefig(root / "recall_and_counts_by_iter.png", dpi=150)


@app.command("prompt-eval")
@async_run
async def prompt_eval(
    prompt: str = typer.Argument(
        ...,
        help="Candidate critic system prompt to evaluate across specimens",
    ),
    out_dir: Path | None = OPT_OUTPUT_DIR,
) -> None:
    """Evaluate a critic system prompt across all known specimens and emit metrics list."""

    pe_server, _state = build_prompt_eval_server(client=AsyncOpenAI())

    async def _run() -> list[dict]:
        base = find_specimens_base()
        specimens = list_specimen_names(base)
        client = AsyncOpenAI()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = (
            out_dir if out_dir is not None else (pkg_dir() / "runs" / "prompt_eval")
        ) / ts
        root.mkdir(parents=True, exist_ok=True)
        (root / "prompt.txt").write_text(prompt, encoding="utf-8")

        async def one(name: str) -> dict:
            # Reuse the in-proc tool rather than duplicating orchestration
            out_dir_spec = root / name
            out_dir_spec.mkdir(parents=True, exist_ok=True)
            critic_obj = await _run_critic_for_specimen(name, prompt, client, root)
            grade = await grade_critic_output(
                name,
                critic_obj,
                client,
                transcript_out_dir=out_dir_spec,
            )
            row = _metrics_row(grade, specimen=name)
            # Persist full grade.json too
            (out_dir_spec / "grade.json").write_text(
                grade.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return row

        rows: list[dict] = await asyncio.gather(*[one(s) for s in specimens])
        (root / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(json.dumps(rows, indent=2))
        return rows

    await _run()


@app.command("specimen-grade")
@async_run
async def specimen_grade(
    specimen: str = ARG_SPECIMEN,
    critique: Path = OPT_CRITIQUE,
) -> None:
    """Grade a saved critique JSON for a specimen against canonical findings; print concise metrics with fuzzy values."""
    try:
        crit_obj = CriticSubmitPayload.model_validate_json(
            critique.read_text(encoding="utf-8"),
        )
    except Exception as e:
        typer.echo(f"ERROR: failed to parse or validate critique JSON: {e}")
        raise typer.Exit(code=2) from e

    grade = await grade_critic_output(
        specimen,
        crit_obj,
        AsyncOpenAI(),
        transcript_out_dir=critique.parent,
    )
    row = _metrics_row(grade, specimen=specimen)
    typer.echo(json.dumps(row, indent=2))
    # Persist full payload near the input for convenience
    out_path = critique.with_suffix(".grade.json")
    out_path.write_text(grade.model_dump_json(indent=2), encoding="utf-8")


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
    specimen: str = typer.Argument(
        ...,
        help="Specimen slug (under properties/specimens)",
    ),
    issue_id: str = typer.Argument(
        ...,
        help="Issue id to lint (must have should_flag=true)",
    ),
    occurrence: int = typer.Argument(..., help="0-based occurrence index"),
    model: str = OPT_MODEL,
    dry_run: bool = OPT_DRY_RUN,
    gitconfig: Path | None = OPT_GITCONFIG,
) -> None:
    git_path = _resolve_gitconfig(str(gitconfig) if gitconfig else None)
    rc = await run_specimen_lint_issue_async(
        specimen,
        issue_id,
        model=model,
        dry_run=dry_run,
        gitconfig=(str(git_path) if git_path else None),
        occurrence_index=occurrence,
        client=AsyncOpenAI(),
    )
    raise typer.Exit(code=rc)


@app.command("eval-all")
@async_run
async def cmd_eval_all() -> None:
    await run_all_evals(model="gpt-5", gitconfig=None, client=AsyncOpenAI())


@app.command("specimen-exec")
@async_run
async def specimen_exec(
    specimen: str = typer.Argument(..., help="Specimen name/path or manifest"),
    gitconfig: Path | None = OPT_GITCONFIG,
    workdir: Path = OPT_WORKDIR_CRITIC,
    interactive: bool = OPT_INTERACTIVE,
    tty_exec: bool = OPT_TTY_EXEC,
    cmd: list[str] = ARG_CMD_LIST,
) -> None:
    """Execute a command in a container with hydrated specimen mounted at /workspace (RW)."""
    # Resolve gitconfig (optional)
    exec_git = _resolve_gitconfig(str(gitconfig) if gitconfig else None)
    # Docker sanity
    try:
        dclient = docker.from_env()
        dclient.ping()
    except Exception as e:
        typer.echo(f"ERROR: Docker daemon not reachable: {e}")
        raise typer.Exit(2) from e
    ensure_critic_image()

    rec = SpecimenRegistry.load_strict(
        specimen if "/" not in specimen else Path(specimen).name,
    )
    async with rec.hydrated_copy(exec_git) as content_root:
        try:
            _ = next(content_root.iterdir())
        except StopIteration:
            typer.echo(f"ERROR: hydrated specimen is empty: {content_root}")
            raise typer.Exit(2) from None
        name = f"adgn_spec_shell_{int(time.time())}"
        volumes, _defs = build_critic_volumes(
            content_root,
            mount_properties=True,
            workspace_mode="rw",
        )
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


def main() -> None:
    """Console entrypoint that invokes the Typer app."""
    app()


if __name__ == "__main__":
    app()  # for direct execution during migration
