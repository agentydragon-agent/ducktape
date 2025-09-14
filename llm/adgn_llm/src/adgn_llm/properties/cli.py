from __future__ import annotations

import asyncio
import argparse
import importlib
import json
import shutil
import subprocess
import tempfile
import docker
from adgn_llm.properties.docker_env import (
    PROPERTIES_DOCKER_IMAGE,
    WORKING_DIR as CRITIC_WORKDIR,
    ensure_critic_image,
    properties_docker_spec,
    build_critic_volumes,
    SLEEP_FOREVER_CMD,
    PropertiesDockerWiring,
)
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

from typing import Mapping, cast, Literal

from adgn_llm.logging_config import configure_logging
import tiktoken
from openai import AsyncOpenAI
from rich.console import Console

from adgn_llm.mini_codex.agent import MiniCodex, ResponsesClient, AgentResult
from adgn_llm.mini_codex.aggregating_handler import BaseHandler
from adgn_llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn_llm.mini_codex.loop_control import Continue, Abort, RequireAny, Forbid
from adgn_llm.mini_codex.mcp_manager import (
    McpManager,
    build_mcp_function,
)
from adgn_llm.mini_codex.transcript_handler import TranscriptHandler
from adgn_llm.properties.agent_runner import run_prompt_async
from adgn_llm.properties.critic import (
    CriticSubmitState,
    CriticSubmitPayload,
    make_critic_submit_server,
)
from adgn_llm.properties.grader import GradeSubmitState, make_grader_submit_server
from adgn_llm.properties.grade_runner import _metrics_row
from adgn_llm.properties.prompts.util import build_input_schemas_json, build_scope_text
from adgn_llm.properties.specimens.registry import SpecimenRegistry
from adgn_llm.properties.prompts.builder import (
    build_role_prompt,
    build_enforce_prompt,
    build_grade_from_json_prompt,
)
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.types import ServerSlotSpec
from adgn_llm.rendering.rich_renderers import render_to_rich
from adgn_llm.prompt_eval.server import (
    _run_critic_for_specimen,
    build_server as build_prompt_eval_server,
)
from adgn_llm.properties.grade_runner import grade_critic_output
from adgn_llm.properties.specimens.registry import (
    find_specimens_base,
    list_specimen_names,
    resolve_manifest_arg,
)
from adgn_llm.properties.prop_utils import pkg_dir
from adgn_llm.properties.models.issue import Occurrence, LineRange, IssueCore


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


# --- Jinja2 template helpers ---


@dataclass(frozen=True)
class BuildOptions:
    sandbox: str
    skip_git_repo_check: bool
    full_auto: bool
    extra_configs: list[str] | None = None


# Human-facing catalog for CLI table (name, category, description)
TOOL_CATALOG: list[tuple[str, str, str]] = [
    ("ruff", "lint/format", "Fast linter/formatter replacing flake8/isort/pyupgrade"),
    ("mypy", "typing", "Static type checker"),
    ("pyright", "typing", "Fast static type checker"),
    ("vulture", "dead code", "Find unused code"),
    ("bandit", "security", "Find common security issues"),
    ("pip-audit", "security", "Audit Python dependencies for CVEs"),
    ("safety", "security", "Scan dependencies for known vulnerabilities"),
    ("codespell", "style", "Spell checker for code/docs"),
    ("pyupgrade", "modernize", "Rewrite code to modern Python syntax"),
    ("refurb", "modernize", "Refactor suggestions"),
    ("flynt", "modernize", "Convert to f-strings"),
    ("pydocstyle", "docs", "Docstring style checker"),
    ("interrogate", "docs", "Docstring coverage"),
    ("import-linter", "architecture", "Enforce import layer contracts"),
    ("semgrep", "patterns", "Multi-language pattern rules with autofix"),
    ("radon", "complexity", "Cyclomatic complexity/maintainability"),
    ("xenon", "complexity", "CI gate using radon thresholds"),
    ("pylint", "duplicates", "Includes duplicate-code (R0801) detector"),
    ("lizard", "duplicates", "Complexity and clone detection"),
    ("coverage", "coverage", "Code coverage measurement"),
    ("diff-cover", "coverage", "Changed-line coverage gating"),
    ("jscpd", "duplicates(node)", "Language-agnostic copy/paste detector (via npx)"),
]


def _format_tools_table(available: list[str]) -> str:
    avail_set = set(available)
    header = ("Avail", "Tool", "Category", "Description")
    lines = [
        f"{header[0]:<5}  {header[1]:<12}  {header[2]:<14}  {header[3]}",
        f"{'-' * 5}  {'-' * 12}  {'-' * 14}  {'-' * 40}",
    ]
    for name, cat, desc in TOOL_CATALOG:
        status = (
            "yes"
            if name in avail_set or (name == "jscpd" and "jscpd(npx)" in avail_set)
            else "no"
        )
        lines.append(f"{status:<5}  {name:<12}  {cat:<14}  {desc}")
    return "\n".join(lines)


def _detect_tools() -> list[str]:
    """Detect optional QA tools on PATH and return friendly names in stable order.
    Also detects jscpd via `npx --no-install` if not directly installed.
    """
    tools = [
        ("ruff", "ruff"),
        ("mypy", "mypy"),
        ("pyright", "pyright"),
        ("vulture", "vulture"),
        ("bandit", "bandit"),
        ("pip-audit", "pip-audit"),
        ("safety", "safety"),
        ("codespell", "codespell"),
        ("pyupgrade", "pyupgrade"),
        ("refurb", "refurb"),
        ("flynt", "flynt"),
        ("pydocstyle", "pydocstyle"),
        ("interrogate", "interrogate"),
        ("import-linter", "lint-imports"),
        ("semgrep", "semgrep"),
        ("radon", "radon"),
        ("xenon", "xenon"),
        ("pylint", "pylint"),
        ("lizard", "lizard"),
        ("coverage", "coverage"),
        ("diff-cover", "diff-cover"),
        ("jscpd", "jscpd"),
    ]
    available: list[str] = []
    for name, exe in tools:
        if shutil.which(exe):
            available.append(name)
    # Special case: try Node-based jscpd via npx without installing
    if "jscpd" not in available and shutil.which("npx"):
        cp = subprocess.run(
            ["npx", "--yes", "--no-install", "jscpd", "--version"],
            check=False,
            text=True,
            capture_output=True,
        )
        if cp.returncode == 0:
            available.append("jscpd(npx)")
    return available


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


def build_cmd(model: str, workdir: Path, opts: BuildOptions) -> list[str]:
    # Use codex exec with long flags for model/sandbox; pass configs via -c
    cmd: list[str] = [
        "codex",
        "exec",
        "--model",
        model,
        "--sandbox",
        opts.sandbox,
        "-C",
        str(workdir),
    ]
    if opts.extra_configs:
        for c in opts.extra_configs:
            cmd.extend(["-c", c])
    if opts.full_auto:
        cmd.append("--full-auto")
    if opts.skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    return cmd


# ---- MiniCodex helpers for check/specimen/grade (docker for code scans) ----
# Handler that forces a tool call each turn and stops when critic_submit.submit_result is called.
class CriticHandler(BaseHandler):
    def __init__(self, state: CriticSubmitState) -> None:
        self._state = state

    def on_before_sample(self):  # type: ignore[override]
        if self._state.result is not None:
            return Abort()
        return Continue(RequireAny())


class PromptOptimizeHandler(BaseHandler):
    """Stop after N successful evaluations tracked by the MCP server.

    Reads successful call count from shared MCP state and enforces budget.
    After budget is exhausted, allows one final non-tool assistant message, then aborts.
    """

    def __init__(self, *, state, max_iters: int) -> None:
        self._state = state
        self._max_iters = max_iters
        self._finalizing = False
        self._done = False

    def on_assistant_text(self, text: str) -> None:  # type: ignore[override]
        if self._finalizing and text:
            self._done = True

    def on_before_sample(self):  # type: ignore[override]
        if self._done:
            return Abort()
        if getattr(self._state, "successful_calls", 0) < self._max_iters:
            return Continue(RequireAny())
        if not self._finalizing:
            self._finalizing = True
            return Continue(Forbid())
        return Abort()


async def _run_minicodex_simple(
    prompt: str,
    model: str,
    specs: Mapping[str, ServerSlotSpec],
    *,
    output_final_message: Path | None = None,
    final_only: bool = False,
    client: AsyncOpenAI,
) -> int:
    # Delegate execution to agent_runner.run_prompt_async so event loop control remains at callers
    res = await run_prompt_async(
        prompt, model, specs, client=client, capture_transcript=not final_only
    )
    if output_final_message:
        Path(output_final_message).write_text(res.final_text, encoding="utf-8")
    if not final_only and res.final_text:
        print(res.final_text)
    return 0


async def _run_check_minicodex_async(
    workdir: Path,
    prompt: str,
    *,
    model: str,
    output_final_message: Path | None,
    final_only: bool,
    client: AsyncOpenAI,
) -> int:
    # Mount the provided workdir read-only and property definitions read-only
    wiring = properties_docker_spec(workdir, mount_properties=True)
    specs = {wiring.server_name: wiring.server_spec}
    # Use agent_runner to execute prompt via MCP; keep event loop in CLI
    res = await run_prompt_async(
        prompt, model, specs, client=client, capture_transcript=not final_only
    )
    if output_final_message:
        Path(output_final_message).write_text(res.final_text, encoding="utf-8")
    if not final_only and res.final_text:
        print(res.final_text)
    return 0


async def _run_specimen_minicodex_async(
    manifest_path: Path,
    *,
    dry_run: bool,
    embed_paths: list[str] | None,
    gitconfig: Path | None,
    mode: str,
    final_only: bool,
    output_final_message: Path | None,
    client: AsyncOpenAI,
) -> int:
    rec = SpecimenRegistry.load_strict(manifest_path.parent.name)
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
                client=cast(ResponsesClient, client),
                handlers=[
                    CriticHandler(submit_state),
                    DisplayEventsHandler(max_lines=10),
                ],
                parallel_tool_calls=True,
            )
            result = await agent.run(prompt)
            if isinstance(result, AgentResult):
                if output_final_message:
                    Path(output_final_message).write_text(
                        result.text or "", encoding="utf-8"
                    )
                if not final_only and result.text:
                    print(result.text)
        assert submit_state.result, "Critic did not call submit_result?"
        Console().print(render_to_rich(submit_state.result))
        # Write critique JSON for specimen-check runs (find/open modes)
        if mode in ("find", "open"):
            ts = int(time.time())
            out_dir = (
                Path.cwd()
                / "runs"
                / "specimen-check"
                / f"{manifest_path.parent.name}_{ts}"
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "critique.json"
            obj = submit_state.result
            s = obj.model_dump_json(indent=2)  # type: ignore[attr-defined]
            out_path.write_text(s, encoding="utf-8")
            print(f"Saved critique JSON: {out_path}")
        return 0


async def _run_specimen_grade_minicodex_async(
    manifest_path: Path,
    critique_path: Path,
    *,
    dry_run: bool,
    final_only: bool,
    output_final_message: Path | None,
    client: AsyncOpenAI,
) -> int:
    rec = SpecimenRegistry.load_strict(manifest_path.parent.name)
    man = rec.manifest
    scope_text = build_scope_text(man.scope.include, man.scope.exclude)

    # Canonical positives → list of {core, occurrences}
    canonical_list = [
        {
            "core": it.core.model_dump(exclude_none=True),
            "occurrences": [occ.model_dump(exclude_none=True) for occ in it.instances],
        }
        for it in rec.issues.values()
    ]
    # Known false positives (optional) → list of {core, occurrences}
    known_fp_list = (
        [
            {
                "core": it.core.model_dump(exclude_none=True),
                "occurrences": [
                    occ.model_dump(exclude_none=True) for occ in it.instances
                ],
            }
            for it in rec.false_positives.values()
        ]
        if hasattr(rec, "false_positives") and rec.false_positives
        else []
    )

    # Read critique JSON produced by specimen-check
    crit_text = Path(critique_path).read_text(encoding="utf-8")
    try:
        # Validate it's JSON; keep original text for prompt
        _ = json.loads(crit_text)
    except Exception:
        print(f"ERROR: critique is not valid JSON: {critique_path}")
        return 2

    wiring = PropertiesDockerWiring(
        server_spec=None,  # no docker servers needed for grading
        # TODO(mpokorny): Provide specimen container access (mount workspace) if we want grader to inspect files
        working_dir=Path("/"),
        definitions_container_dir=None,
        image_name="n/a",
    )
    submit_state = GradeSubmitState()
    grader_server = make_grader_submit_server(submit_state, name="grader_submit")

    prompt = build_grade_from_json_prompt(
        scope_text=scope_text,
        canonical_json=json.dumps(canonical_list, ensure_ascii=False, indent=2),
        critique_json=crit_text,
        known_fp_json=(
            json.dumps(known_fp_list, ensure_ascii=False, indent=2)
            if known_fp_list
            else "[]"
        ),
        submit_tool_name=build_mcp_function("grader_submit", "submit_result"),
        wiring=wiring,
    )

    if dry_run:
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        outfile = tmpdir / f"codex_prompt_specimen_grade_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        tokens = len(tiktoken.get_encoding("cl100k_base").encode(prompt))
        print(
            f"Saved prompt: {outfile} (approx tokens: {tokens if tokens is not None else 'n/a'})"
        )
        return 0

    # MiniCodex run with in-proc grader_submit server; force tool calls until submit
    class GraderHandler(BaseHandler):
        def __init__(self, state: GradeSubmitState) -> None:
            self._state = state

        def on_before_sample(self):  # type: ignore[override]
            if self._state.result is not None:
                return Abort()
            return Continue(RequireAny())

    specs = {"grader_submit": make_inproc_slot_spec(grader_server)}
    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model="gpt-5",
            mcp=mcp,
            system="You are a code agent. Be concise.",
            client=cast(ResponsesClient, client),
            handlers=[GraderHandler(submit_state), DisplayEventsHandler(max_lines=10)],
            parallel_tool_calls=True,
        )
        result = await agent.run(prompt)
        if isinstance(result, AgentResult):
            if output_final_message:
                Path(output_final_message).write_text(
                    result.text or "", encoding="utf-8"
                )
            if not final_only and result.text:
                print(result.text)

    assert submit_state.result, "Grader did not call submit_result?"
    Console().print(render_to_rich(submit_state.result))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    client = AsyncOpenAI()

    parser = argparse.ArgumentParser(
        description="adgn-llm codex properties CLI",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Check for violations under a static path set\n"
            "  adgn-properties check $(pwd) 'all files under src/**' --dry-run\n\n"
            "  # Fix code on a path set (workspace-write sandbox)\n"
            "  adgn-properties fix $(pwd) 'all files under src/**'\n\n"
            "  # Check saved specimen by name (uses manifest.yaml)\n"
            "  adgn-properties specimen-check 2025-09-02-ducktape_wt --dry-run\n\n"
            "  # Discover new findings vs specimen notes\n"
            "  adgn-properties specimen-discover 2025-09-02-ducktape_wt --dry-run\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("workdir")
    common.add_argument("scope")
    common.add_argument("-m", "--model", default="gpt-5")
    common.add_argument("--dry-run", action="store_true")
    common.add_argument("--skip-git-repo-check", action="store_true")
    common.add_argument("--full-auto", action="store_true")
    common.add_argument(
        "--allow-general-findings",
        action="store_true",
        help="Also allow general code-quality findings beyond formal properties",
    )
    common.add_argument(
        "--final-only",
        action="store_true",
        help="Print only the agent's final message to stdout (suppresses trajectory output)",
    )
    common.add_argument(
        "--output-final-message",
        help="Write only the agent's final message to this path (passthrough to codex --output-last-message)",
    )

    sub.add_parser(
        "check",
        parents=[common],
        help="Check for violations using committed property definitions",
        description=(
            "Analyze code within the provided scope against all committed property definitions.\n"
            "- workdir: repo or directory to analyze\n"
            "- scope: freeform description (diff or static files), e.g. 'all files under src/**'\n"
            "Outputs a structured report; does not modify files."
        ),
    )
    sub.add_parser(
        "fix",
        parents=[common],
        help="Refactor code within scope to satisfy property definitions",
        description=(
            "Edit code to bring it into compliance with committed property definitions.\n"
            "- Uses a workspace-write sandbox\n"
            "- Keeps edits minimal and scoped; runs linters/formatters if present"
        ),
    )

    # Specimen runner subcommand (integrated)
    p_spec = sub.add_parser(
        "specimen-check",
        help="Run property scan on a saved specimen, by specimen name",
    )
    p_spec.add_argument(
        "specimen",
        nargs="?",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml",
    )
    p_spec.add_argument("--dry-run", action="store_true")
    p_spec.add_argument(
        "--embed-path",
        action="append",
        dest="embed_paths",
        help="Extra files to embed into the prompt (Markdown); repeatable",
    )
    p_spec.add_argument(
        "--gitconfig",
        help="Path to a gitconfig to use for private repo fallback (shallow git)",
    )
    p_spec.add_argument(
        "--final-only",
        action="store_true",
        help="Print only the agent's final message to stdout (suppresses trajectory output)",
    )
    p_spec.add_argument(
        "--output-final-message",
        help="Write only the agent's final message to this path (passthrough to codex --output-last-message)",
    )
    p_spec.add_argument(
        "--allow-general-findings",
        action="store_true",
        help="Also allow general code-quality findings beyond formal properties",
    )

    # New command: specimen-discover — report only new findings vs current specimen notes
    p_spec_new = sub.add_parser(
        "specimen-discover",
        help="Discover only-new issues vs specimen notes",
        description=(
            "Run a scan on a specimen but suppress anything already listed in covered.md/not_covered_yet.md.\n"
            "Reports only additional instances, new categories under existing properties, or entirely new issues."
        ),
    )
    p_spec_new.add_argument(
        "specimen",
        nargs="?",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml",
    )
    p_spec_new.add_argument("--dry-run", action="store_true")
    p_spec_new.add_argument(
        "--gitconfig",
        help="Path to a gitconfig to use for private repo fallback (shallow git)",
    )
    p_spec_new.add_argument(
        "--final-only",
        action="store_true",
        help="Print only the agent's final message to stdout (suppresses trajectory output)",
    )
    p_spec_new.add_argument(
        "--output-final-message",
        help="Write only the agent's final message to this path (passthrough to codex --output-last-message)",
    )
    p_spec_new.add_argument(
        "--allow-general-findings",
        action="store_true",
        help="Also allow general code-quality findings beyond formal properties",
    )

    # New command: specimen-grade — grade an input critique against canonical specimen notes
    p_spec_grade = sub.add_parser(
        "specimen-grade",
        help="Grade an input critique vs canonical specimen findings (covered/not_covered_yet/false_positives)",
        description=(
            "Compute recall and false-positive ratio by matching an input critique against the specimen's\n"
            "covered.md + not_covered_yet.md (positives) and false_positives.md (negatives). Output plaintext/MD."
        ),
    )
    p_spec_grade.add_argument(
        "specimen",
        nargs="?",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml",
    )
    p_spec_grade.add_argument(
        "--critique",
        required=True,
        help="Path to the input critique text file to grade",
    )
    p_spec_grade.add_argument("--dry-run", action="store_true")
    p_spec_grade.add_argument(
        "--gitconfig",
        help="Path to a gitconfig to use for private repo fallback (shallow git)",
    )
    p_spec_grade.add_argument(
        "--final-only",
        action="store_true",
        help="Print only the agent's final message to stdout (suppresses trajectory output)",
    )
    p_spec_grade.add_argument(
        "--output-final-message",
        help="Write only the agent's final message to this path (passthrough to codex --output-last-message)",
    )

    # New command: prompt-eval — evaluate a candidate critic system prompt across all specimens
    p_pe = sub.add_parser(
        "prompt-eval",
        help="Evaluate a candidate critic system prompt across all known specimens (returns only metrics)",
    )
    p_pe.add_argument(
        "--prompt", required=True, help="Candidate system prompt for critic agent"
    )
    p_pe.add_argument(
        "--out-dir",
        dest="out_dir",
        help="Root directory for run artifacts (default: runs/prompt_eval)",
    )

    # New command: prompt-optimize — run a PE agent that iteratively optimizes a critic system prompt using the prompt_eval MCP tool
    p_pe_opt = sub.add_parser(
        "prompt-optimize",
        help="Run a Prompt Engineering agent that optimizes a critic system prompt over all specimens",
        description=(
            "Launch a PE agent that uses the prompt_eval MCP tool to evaluate candidate critic prompts across all specimens, "
            "iterating up to a fixed evaluation budget. Shows progress and writes artifacts under runs/prompt_optimize/."
        ),
    )
    p_pe_opt.add_argument(
        "--max-iters",
        type=int,
        default=10,
        help="Maximum number of prompt evaluations (tool calls)",
    )
    p_pe_opt.add_argument(
        "--out-dir",
        dest="out_dir",
        help="Root directory for run artifacts (default: runs/prompt_optimize)",
    )
    p_pe_opt.add_argument(
        "--context",
        choices=["minimal", "props"],
        default="minimal",
        help="Prompt-eval agent context: 'minimal' (no extra servers) or 'props' (mount /props via docker MCP)",
    )

    # New command: lint-issue — lint exactly one issue using mini_codex + docker_exec MCP
    p_spec_lint = sub.add_parser(
        "lint-issue",
        help="Lint a single issue in a specimen (mini_codex + docker_exec)",
        description=(
            "Lint/check a single instance of an issue on a specimen - for propery property definition linkage, etc."
        ),
    )
    p_spec_lint.add_argument(
        "specimen",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml",
    )
    p_spec_lint.add_argument(
        "issue_id",
        help="Issue id to lint (must have should_flag=true)",
    )
    p_spec_lint.add_argument("--model", default="gpt-5")
    p_spec_lint.add_argument("--dry-run", action="store_true")
    p_spec_lint.add_argument(
        "occurrence",
        type=int,
        help="0-based occurrence index within issue.instances",
    )
    p_spec_lint.add_argument(
        "--gitconfig",
        help="Path to a gitconfig to use for private repo fallback (shallow git)",
    )

    # New command: eval-lint-issue — run eval harness for a single issue with cases file
    p_eval = sub.add_parser(
        "eval-lint-issue",
        help="Run eval harness for a lint-issue across multiple cases",
        description=(
            "Run the lint-issue agent for a specimen/issue across cases defined in a JSON file, "
            "writing artifacts and a summary.json under runs/evals/."
        ),
    )
    p_eval.add_argument("specimen", help="Specimen name/dir/issues.libsonnet path")
    p_eval.add_argument("issue_id", help="Issue id (must exist in specimen issues)")
    p_eval.add_argument(
        "--cases", required=True, help="Path to cases file (JSON list of dicts)"
    )
    p_eval.add_argument(
        "--out-dir", dest="out_dir", help="Output directory for eval artifacts"
    )
    p_eval.add_argument("--model", default="gpt-5")
    p_eval.add_argument("--gitconfig")

    # New command: specimen-exec — execute a command inside the hydrated specimen container (RW mount)
    p_spec_shell = sub.add_parser(
        "specimen-exec",
        help="Execute a command in a container with the hydrated specimen mounted",
        description=(
            "Hydrate specimen into a temporary workspace and execute the provided command\n"
            "inside a container with the workspace mounted at /workspace (read-write). Container uses no network and is removed on exit."
        ),
    )
    p_spec_shell.add_argument(
        "specimen",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to issues.libsonnet",
    )
    p_spec_shell.add_argument(
        "--gitconfig",
        help="Path to a gitconfig to use for private repo fallback (shallow git)",
    )
    p_spec_shell.add_argument(
        "--workdir",
        default=str(CRITIC_WORKDIR),
        help="Container working directory (default: /workspace)",
    )
    # Interactive stdio/PTY wiring for docker exec (use -i and/or -t)
    p_spec_shell.add_argument(
        "-i",
        dest="interactive",
        action="store_true",
        help="Attach STDIN for docker exec (equivalent to 'docker exec -i')",
    )
    p_spec_shell.add_argument(
        "-t",
        dest="tty_exec",
        action="store_true",
        help="Allocate a TTY for docker exec (equivalent to 'docker exec -t')",
    )
    p_spec_shell.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to run after '--' (required)",
    )

    # Eval harness: run all registered datasets (no options to keep CLI stable)
    sub.add_parser(
        "eval-all",
        help="Run all registered eval datasets",
        description="Runs all datasets and writes runs/evals/<ts>/index.json.",
    )

    args = parser.parse_args(argv)

    if args.command == "lint-issue":
        # Late import via importlib to avoid circular dependency while keeping lints happy
        mod = importlib.import_module("adgn_llm.properties.lint_issue")
        client = client
        return asyncio.run(
            mod.run_specimen_lint_issue_async(
                args.specimen,
                args.issue_id,
                model=getattr(args, "model", "gpt-5"),
                dry_run=getattr(args, "dry_run", False),
                gitconfig=getattr(args, "gitconfig", None),
                occurrence_index=getattr(args, "occurrence"),
                client=client,
            )
        )

    if args.command == "eval-all":
        eval_mod = importlib.import_module("adgn_llm.properties.eval_harness")
        # Run evals silently (no rollout console output); artifacts written under runs/evals/
        asyncio.run(
            eval_mod.run_all_evals(
                model="gpt-5",
                gitconfig=None,
                client=client,
            )
        )
        return 0

    if args.command == "eval-lint-issue":
        # Lazy import to avoid cycles
        mod = importlib.import_module("adgn_llm.properties.eval_harness")
        cases_path = Path(getattr(args, "cases"))
        if not cases_path.exists():
            print(f"ERROR: cases file not found: {cases_path}")
            return 2
        try:
            cases = json.loads(cases_path.read_text(encoding="utf-8"))
            if not isinstance(cases, list):
                print("ERROR: cases file must contain a top-level list of case dicts")
                return 2
        except Exception as e:
            print(f"ERROR: failed to parse cases JSON: {e}")
            return 2
        client = client
        out_dir = getattr(args, "out_dir", None)
        # Resolve optional gitconfig with fallback to properties/gitconfig.local
        gitconfig_eval = _resolve_gitconfig(getattr(args, "gitconfig", None))
        path = asyncio.run(
            mod.eval_lint_issue_cases(
                getattr(args, "specimen"),
                getattr(args, "issue_id"),
                cases,
                model=getattr(args, "model", "gpt-5"),
                gitconfig=gitconfig_eval,
                client=client,
                out_dir=out_dir,
            )
        )
        print(f"Eval summary written to: {path / 'summary.json'}")
        return 0

    if args.command == "specimen-check":
        base = find_specimens_base()
        manifest_path = resolve_manifest_arg(args.specimen, base)
        if manifest_path is None:
            names = list_specimen_names(base)
            if not names:
                print(f"No specimens found under: {base}")
                return 2
            print("Available specimens:")
            for n in names:
                print(" -", n)
            return 0
        # Validate gitconfig if provided
        gitconfig_path = _resolve_gitconfig(getattr(args, "gitconfig", None))
        mode = "open" if getattr(args, "allow_general_findings", False) else "find"
        return asyncio.run(
            _run_specimen_minicodex_async(
                manifest_path,
                dry_run=args.dry_run,
                embed_paths=args.embed_paths,
                gitconfig=gitconfig_path,
                mode=mode,
                final_only=getattr(args, "final_only", False),
                output_final_message=args.output_final_message,  # TODO: make the type Path
                client=AsyncOpenAI(),
            )
        )

    if args.command == "specimen-discover":
        base = find_specimens_base()
        manifest_path = resolve_manifest_arg(args.specimen, base)
        if not manifest_path:
            if not (names := list_specimen_names(base)):
                print(f"No specimens under {base}")
                return 2
            print("Available specimens:")
            for n in names:
                print(" -", n)
            return 0
        gitconfig_path = _resolve_gitconfig(getattr(args, "gitconfig", None))
        # Embed existing findings to suppress repeats
        embed_paths = [
            str(pth)
            for name in ("covered.md", "not_covered_yet.md")
            if (pth := manifest_path.parent / name).exists()
        ]
        return asyncio.run(
            _run_specimen_minicodex_async(
                manifest_path,
                dry_run=args.dry_run,
                embed_paths=embed_paths,
                gitconfig=gitconfig_path,
                mode="discover",
                final_only=getattr(args, "final_only", False),
                output_final_message=getattr(args, "output_final_message", None),
                client=AsyncOpenAI(),
            )
        )

    if args.command == "specimen-grade":
        base = find_specimens_base()
        if not (manifest_path := resolve_manifest_arg(args.specimen, base)):
            names = list_specimen_names(base)
            if not names:
                print(f"No specimens found under: {base}")
                return 2
            print("Available specimens:")
            for n in names:
                print(" -", n)
            return 2
        crit_path = Path(args.critique).expanduser().resolve()
        if not crit_path.exists():
            print(f"ERROR: critique file not found: {crit_path}")
            return 2
        try:
            crit_json = json.loads(crit_path.read_text(encoding="utf-8"))
            critique = CriticSubmitPayload.model_validate(crit_json)
        except Exception as e:
            print(f"ERROR: failed to parse or validate critique JSON: {e}")
            return 2

        # Run grader via shared grade_runner (no duplicate wiring here)
        async def _run() -> int:
            grade = await grade_critic_output(
                manifest_path.parent.name, critique, AsyncOpenAI()
            )
            # Print concise metrics including fuzzy values
            row = _metrics_row(grade, specimen=manifest_path.parent.name)
            print(json.dumps(row, indent=2))
            # Persist to runs/specimen-grade/<ts>
            ts_dir = Path.cwd() / "runs" / "specimen-grade"
            ts_dir.mkdir(parents=True, exist_ok=True)
            (ts_dir / f"{manifest_path.parent.name}.grade.json").write_text(
                grade.model_dump_json(), encoding="utf-8"
            )
            return 0

        return asyncio.run(_run())

    if args.command == "prompt-eval":
        prompt = getattr(args, "prompt")
        out_root = (
            Path(args.out_dir).expanduser().resolve()
            if getattr(args, "out_dir", None)
            else None
        )

        async def _run_pe() -> int:
            base = find_specimens_base()
            specimens = list_specimen_names(base)
            client = AsyncOpenAI()
            # run dir

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = (
                out_root
                if out_root is not None
                else (pkg_dir() / "runs" / "prompt_eval")
            ) / ts
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

            async def one(s: str):
                critic_obj = await _run_critic_for_specimen(s, prompt, client, run_dir)
                out_dir = run_dir / s
                out_dir.mkdir(parents=True, exist_ok=True)
                grade_obj = await grade_critic_output(
                    s, critic_obj, client, transcript_out_dir=out_dir
                )
                (out_dir / "grade.json").write_text(
                    grade_obj.model_dump_json(indent=2), encoding="utf-8"
                )
                critic_log = out_dir / "critic" / "events.jsonl"
                grader_log = out_dir / "grader" / "events.jsonl"
                print(f"[logs] critic: {critic_log}")
                print(f"[logs] grader: {grader_log}")
                m = grade_obj.metrics
                print(
                    f"[metrics] specimen={s} expected={m.expected} reported={m.reported} "
                    f"tp={m.true_positives} fp={m.false_positive} unk={m.unknown} fn={m.false_negatives} "
                    f"precision={m.precision:.3f} recall={m.recall:.3f}"
                )
                return m.model_dump()

            metrics_list = await asyncio.gather(*[one(s) for s in specimens])
            (run_dir / "results.json").write_text(
                json.dumps(metrics_list, indent=2), encoding="utf-8"
            )
            print(json.dumps(metrics_list, indent=2))
            return 0

        return asyncio.run(_run_pe())

    if args.command == "prompt-optimize":
        max_iters = int(getattr(args, "max_iters", 10))
        out_root = (
            Path(args.out_dir).expanduser().resolve()
            if getattr(args, "out_dir", None)
            else (
                pkg_dir()
                / "runs"
                / "prompt_optimize"
                / datetime.now().strftime("%Y%m%d_%H%M%S")
            )
        )
        out_root.mkdir(parents=True, exist_ok=True)
        # In-proc prompt_eval MCP server
        pe_server, pe_state = build_prompt_eval_server()
        specs = {"prompt_eval": make_inproc_slot_spec(pe_server)}
        # PE agent prompts
        pe_system = (
            "You are an expert LLM prompt engineer.\n\n"
            "You can evaluate performance of a given prompt using prompt_eval.test_prompt(prompt: str).\n\n"
            "You will have a given maximum budget of prompt_eval.test_prompt calls. Wisely trade off exploration and exploitation."
        )
        pe_user = (
            f"Your budget is: {max_iters} prompt_eval.test_prompt calls."
            "\n\n"
            "Iterate to find an optimal prompt for a code reviewer/critic LLM agent."
            "\n\n"
            "Your priorities are: recall first, then precision."
            "\n\n"
            "Your prompt will in a harness that ensures the critic follows required downstream format. "
            "As such, do not give the critic any prescription on which specific format to use (e.g., JSON)."
        )
        # Optionally add a docker MCP server with /props mounted
        if getattr(args, "context", "minimal") == "props":
            from adgn_llm.properties.docker_env import (
                properties_docker_spec,
                SERVER_NAME as DOCKER_SERVER_NAME,
                PROPS_DIR,
            )

            wiring = properties_docker_spec(pkg_dir(), mount_properties=True)
            specs[DOCKER_SERVER_NAME] = wiring.server_spec
            pe_user += f"\n\nYou also have a docker MCP server '{DOCKER_SERVER_NAME}'."
            pe_user += (
                f"\n\nRead content at {PROPS_DIR} to find some *nonexhaustive* examples of properties of good code critics should enforce. "
                "Note that these are only some specific formal examples that we captured formally - many issues we want to catch are not covered yet by any of these formal properties."
            )
            pe_user += f"\n\nThe critic agent will run on the same Docker image as you have available."

        async def _run_pe_agent() -> int:
            async with McpManager(specs) as mcp:
                agent = await MiniCodex.create(
                    model="gpt-5",
                    mcp=mcp,
                    system=pe_system,
                    client=AsyncOpenAI(),
                    handlers=[
                        TranscriptHandler(dest_dir=out_root / "prompt_optimize"),
                        DisplayEventsHandler(max_lines=10),
                        PromptOptimizeHandler(state=pe_state, max_iters=max_iters),
                    ],
                    parallel_tool_calls=True,
                )
                # Display progress by streaming events via DisplayEventsHandler; final text printed below
                pe_log = out_root / "prompt_optimize" / "events.jsonl"
                print(f"[logs] prompt_optimize: {pe_log}")
                res = await agent.run(pe_user)
                ts = int(time.time())
                (out_root / f"final_{ts}.md").write_text(
                    getattr(res, "text", ""), encoding="utf-8"
                )
                if getattr(res, "text", ""):
                    print(res.text)
            return 0

        return asyncio.run(_run_pe_agent())

    if args.command in ("check", "fix"):
        workdir = Path(args.workdir).resolve()
        detected_tools = _detect_tools()
        if not getattr(args, "output_final_message", None):
            print(
                f"Detected tools    : {', '.join(detected_tools) if detected_tools else '(none)'}",
            )
            print(_format_tools_table(detected_tools))
        out_last_file: Path | None = None
        if args.command == "check":
            wiring = properties_docker_spec(workdir, mount_properties=True)
            role_mode: Literal["find", "open", "discover"] = (
                "open" if args.allow_general_findings else "find"
            )
            prompt = build_role_prompt(
                role_mode,
                args.scope,
                wiring=wiring,
                supplemental_text=None,
                available_tools=detected_tools,
            )
            # MiniCodex path for check: run inside docker (RO mount)
            if args.dry_run:
                tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
                tmpdir.mkdir(parents=True, exist_ok=True)
                ts = int(time.time())
                outfile = tmpdir / f"codex_prompt_{args.command}_{ts}.md"
                outfile.write_text(prompt, encoding="utf-8")
                enc = tiktoken.get_encoding("cl100k_base")
                tokens = len(enc.encode(prompt))
                print(
                    f"Detected tools: {', '.join(_detect_tools()) if _detect_tools() else '(none)'}",
                )
                print(_format_tools_table(_detect_tools()))
                print(
                    f"Saved prompt: {outfile} (approx tokens: {tokens})",
                )
                return 0
            return asyncio.run(
                _run_check_minicodex_async(
                    workdir,
                    prompt,
                    model=args.model,
                    output_final_message=getattr(args, "output_final_message", None),
                    final_only=args.final_only,
                    client=client,
                )
            )
        else:
            wiring = properties_docker_spec(workdir, mount_properties=True)
            schemas_json = build_input_schemas_json([Occurrence, LineRange, IssueCore])
            prompt = build_enforce_prompt(
                args.scope, wiring=wiring, schemas_json=schemas_json
            )
            cmd = build_cmd(
                args.model,
                workdir,
                BuildOptions(
                    sandbox="workspace-write",
                    skip_git_repo_check=args.skip_git_repo_check,
                    full_auto=args.full_auto,
                    extra_configs=['sandbox_permissions=["disk-full-read-access"]'],
                ),
            )
            if getattr(args, "output_final_message", None):
                cmd.extend(["--output-last-message", args.output_final_message])
            elif args.final_only:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    out_last_file = Path(tmp.name)
                cmd.extend(["--output-last-message", str(out_last_file)])

            if args.dry_run:
                # Save prompt to system temp dir and print approx token count
                tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
                tmpdir.mkdir(parents=True, exist_ok=True)
                ts = int(time.time())
                outfile = tmpdir / f"codex_prompt_{args.command}_{ts}.md"
                outfile.write_text(prompt, encoding="utf-8")
                tokens = None
                enc = tiktoken.get_encoding("cl100k_base")
                tokens = len(enc.encode(prompt))
                print(" ".join(cmd))
                tools = _detect_tools()
                print(f"Detected tools: {', '.join(tools) if tools else '(none)'}")
                print(_format_tools_table(tools))
                print(f"Saved prompt: {outfile} (~{tokens or 'n/a'} tok)")
                return 0

            # Stream to subprocess stdin for fix
            rc = subprocess.run(cmd, check=False, input=prompt, text=True).returncode
            if out_last_file is not None:
                print(Path(out_last_file).read_text(encoding="utf-8"))
            return rc

    if args.command == "specimen-exec":
        base = find_specimens_base()
        manifest_path = resolve_manifest_arg(args.specimen, base)
        if not manifest_path:
            names = list_specimen_names(base)
            if not names:
                print(f"No specimens found under: {base}")
                return 2
            print("Available specimens:")
            for n in names:
                print(" -", n)
            return 2

        if not args.cmd:
            print("ERROR: specimen-exec requires a command after '--'")
            return 2

        exec_gitconfig: Path | None = args.gitconfig
        if exec_gitconfig:
            exec_gitconfig = Path(exec_gitconfig).expanduser().resolve()
            if not exec_gitconfig.exists():
                print(f"ERROR: --gitconfig file not found: {exec_gitconfig}")
                return 2
        else:
            exec_gitconfig = pkg_dir() / "gitconfig.local"
            if not exec_gitconfig.exists():
                exec_gitconfig = None

        try:
            dclient = docker.from_env()
            # Light sanity check; will raise if daemon unavailable
            dclient.ping()
        except Exception as e:
            print(f"ERROR: Docker daemon not reachable: {e}")
            return 2

        ensure_critic_image()

        async def _run_exec() -> int:
            rec = SpecimenRegistry.load_strict(manifest_path.parent.name)
            async with rec.hydrated_copy(exec_gitconfig) as content_root:
                # Sanity: ensure hydrated workspace is not empty before launching container
                try:
                    has_any = any(content_root.iterdir())
                except Exception:
                    has_any = False
                if not has_any:
                    print(f"ERROR: hydrated specimen is empty: {content_root}")
                    return 2
                name = f"adgn_spec_shell_{int(time.time())}"
                container = None
                # Always use the properties critic image and ensure it exists locally
                # Mount repo root directly at /workspace (no intermediate dir)
                volumes, _defs = build_critic_volumes(
                    content_root, mount_properties=True, workspace_mode="rw"
                )
                container = dclient.containers.run(
                    image=PROPERTIES_DOCKER_IMAGE,
                    command=SLEEP_FOREVER_CMD,
                    name=name,
                    remove=True,
                    detach=True,
                    network_mode="none",
                    volumes=volumes,
                    working_dir=str(args.workdir),
                    tty=True,
                    stdin_open=True,
                )
                try:
                    # Execute the provided command; optionally wire up -i/-t (stdio/PTY)
                    exec_cmd = ["docker", "exec"]
                    if getattr(args, "interactive", False):
                        exec_cmd.append("-i")
                    if getattr(args, "tty_exec", False):
                        exec_cmd.append("-t")
                    exec_cmd.append(name)
                    exec_cmd.extend(args.cmd)
                    return subprocess.run(exec_cmd, check=False).returncode
                finally:
                    if container:
                        container.stop()

        return asyncio.run(_run_exec())

    else:
        parser.error("command is required")


if __name__ == "__main__":
    raise SystemExit(main())
