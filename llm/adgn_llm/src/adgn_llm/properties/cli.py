from __future__ import annotations

import asyncio
import argparse
import importlib
import shutil
import subprocess
import sys
import tempfile
import tarfile
import docker
import time
from dataclasses import dataclass
from adgn_llm.properties.prop_utils import properties_root
from pathlib import Path
from jinja2 import Environment, PackageLoader, select_autoescape

from adgn_llm.logging_config import configure_logging
import tiktoken
from openai import AsyncOpenAI
from adgn_llm.properties.lint_issue import DOCKER_IMAGE as _DEFAULT_IMAGE
from importlib import resources
import shutil

from .specimen_utils import (
    build_scope_text,
    find_specimens_base,
    list_specimen_names,
    load_manifest,
    resolve_manifest_arg,
    resolve_source_root,
    ensure_archive_for_specimen_slug,
)




def read_embedded_paths(paths: list[Path]) -> str:
    files_to_embed: list[Path] = []
    for q in paths:
        p = Path(q)
        if p.is_file():
            files_to_embed.append(p)
    blocks: list[str] = []
    for p in sorted(files_to_embed, key=lambda x: str(x)):
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        blocks.append("\n".join([f'<file path=":/{p}">', content, "</file>"]))
    return "\n\n".join(blocks)




def _properties_text() -> str:
    # Load packaged Markdown definitions and wrap each with a file tag that
    # encodes its path relative to the properties/ root, so cross-links are meaningful.
    props_root = properties_root()
    defs_dir = props_root / "definitions"
    parts: list[str] = []
    for md in sorted(defs_dir.rglob("*.md")):
        rel = md.relative_to(props_root)  # e.g., definitions/python/type-hints.md
        parts.append(
            f'<file path=":/{rel.as_posix()}">\n{md.read_text(encoding="utf-8")}\n</file>',
        )
    return "\n\n".join(parts)




# --- Jinja2 template helpers ---


def _get_templates_env() -> Environment:
    # Load prompt templates from the installed package using importlib.resources (via Jinja2 PackageLoader)
    return Environment(
        loader=PackageLoader("adgn_llm.properties", "prompts"),
        autoescape=select_autoescape(["md", "markdown", "txt", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _render_prompt_template(name: str, **ctx: object) -> str:
    env = _get_templates_env()
    tmpl = env.get_template(name)
    return str(tmpl.render(**ctx)).strip()


@dataclass(frozen=True)
class BuildOptions:
    sandbox: str
    skip_git_repo_check: bool
    full_auto: bool
    extra_configs: list[str] | None = None


# Recognized QA tools (names shown to users/agents)
RECOGNIZED_TOOLS: list[str] = [
    "ruff",
    "mypy",
    "pyright",
    "vulture",
    "bandit",
    "pip-audit",
    "safety",
    "codespell",
    "pyupgrade",
    "refurb",
    "flynt",
    "pydocstyle",
    "interrogate",
    "import-linter",
    "semgrep",
    "radon",
    "xenon",
    "pylint",
    "lizard",
    "coverage",
    "diff-cover",
    "jscpd",
    "jscpd(npx)",
]

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
        try:
            cp = subprocess.run(
                ["npx", "--yes", "--no-install", "jscpd", "--version"],
                check=False,
                text=True,
                capture_output=True,
            )
            if cp.returncode == 0:
                available.append("jscpd(npx)")
        except Exception:
            pass
    return available


def build_find_prompt(
    scope_text: str,
    supplemental_text: str | None = None,
    available_tools: list[str] | None = None,
) -> str:
    properties_text = _properties_text()
    return _render_prompt_template(
        "find.md.j2",
        scope_text=scope_text,
        properties_text=properties_text,
        supplemental_text=supplemental_text,
        available_tools=available_tools or [],
        static_action="analyze",
        ambiguity_tail="do not include anything outside it.",
    )


def build_open_review_prompt(
    scope_text: str,
    supplemental_text: str | None = None,
    available_tools: list[str] | None = None,
) -> str:
    properties_text = _properties_text()
    return _render_prompt_template(
        "open_review.md.j2",
        scope_text=scope_text,
        properties_text=properties_text,
        supplemental_text=supplemental_text,
        available_tools=available_tools or [],
        static_action="analyze",
        ambiguity_tail="do not include anything outside it.",
    )


def build_enforce_prompt(scope_text: str, supplemental_text: str | None = None) -> str:
    properties_text = _properties_text()
    return _render_prompt_template(
        "enforce.md.j2",
        scope_text=scope_text,
        properties_text=properties_text,
        supplemental_text=supplemental_text,
        static_action="edit",
        ambiguity_tail="avoid touching anything outside it unless required by the editing policy below.",
    )


def build_grade_prompt(scope_text: str, canonical_text: str, critique_text: str) -> str:
    return _render_prompt_template(
        "grade.md.j2",
        scope_text=scope_text,
        canonical_text=canonical_text,
        critique_text=critique_text,
        static_action="use for context only (do not re-scan code)",
        ambiguity_tail="you are not re-running analysis; only use it for reference while matching.",
    )


def _run_specimen_grade(  # noqa: PLR0913
    manifest_path: Path,
    critique_path: Path,
    *,
    dry_run: bool,
    final_only: bool,
    output_final_message: str | None,
    gitconfig: str | None,
) -> int:
    man = load_manifest(manifest_path)
    # Resolve root (fresh checkout/copy) so the agent has code context
    root = resolve_source_root(man, manifest_path, gitconfig)

    scope_text = build_scope_text(man.scope.include, man.scope.exclude)

    # Collect canonical findings — Jsonnet-only (issues.libsonnet or issues.libsonnet)
    spec_dir = manifest_path.parent
    issues_path = None
    p = spec_dir / "issues.libsonnet"
    if not p.exists():
        print(
            f"ERROR: No issues.libsonnet found under {spec_dir}. "
            "Specimen-grade requires Jsonnet canonical issues; please create issues.libsonnet.",
        )
        return 2
    issues_path = p
    canonical_text = read_embedded_paths([issues_path])
    critique_text = read_embedded_paths([critique_path])

    prompt = build_grade_prompt(scope_text, canonical_text, critique_text)

    # Build codex command (read-only; full-auto; skip git repo check)
    cmd = build_cmd(
        "gpt-5",
        root,
        BuildOptions(sandbox="read-only", skip_git_repo_check=True, full_auto=True),
    )

    out_last_file: Path | None = None
    if output_final_message:
        cmd.extend(["--output-last-message", output_final_message])
    elif final_only:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            out_last_file = Path(tmp.name)
        cmd.extend(["--output-last-message", str(out_last_file)])

    if dry_run:
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        outfile = tmpdir / f"codex_prompt_specimen_grade_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        tokens = None
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = len(enc.encode(prompt))
        print(" ".join(cmd))
        print(
            f"Saved prompt: {outfile} (approx tokens: {tokens if tokens is not None else 'n/a'})",
        )
        return 0

    rc = subprocess.run(cmd, check=False, input=prompt, text=True).returncode
    if out_last_file is not None:
        print(Path(out_last_file).read_text(encoding="utf-8"))
    return rc


def build_cmd(
    model: str,
    workdir: Path,
    opts: BuildOptions,
) -> list[str]:
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


# ---- Specimen helpers moved to specimen_utils; duplicate definitions removed ----


def _run_specimen(  # noqa: PLR0913
    manifest_path: Path,
    *,
    dry_run: bool,
    embed_paths: list[str] | None,
    gitconfig: str | None,
    mode: str = "find",
    final_only: bool = False,
    output_final_message: str | None = None,
) -> int:
    man = load_manifest(manifest_path)
    # Resolve root
    root = resolve_source_root(man, manifest_path, gitconfig)

    scope_text = build_scope_text(man.scope.include, man.scope.exclude)
    # Build supplemental text from embedded files (covered/not_covered_yet or user-specified)
    supplemental_text = (
        read_embedded_paths([Path(p) for p in (embed_paths or [])])
        if embed_paths
        else None
    )
    # Build appropriate prompt
    if mode == "discover":
        prompt = _render_prompt_template(
            "discover.md.j2",
            scope_text=scope_text,
            properties_text=_properties_text(),
            supplemental_text=supplemental_text,
            available_tools=_detect_tools(),
            static_action="analyze",
            ambiguity_tail="do not include anything outside it.",
        )
    elif mode == "open":
        # Open-ended review without suppression
        prompt = build_open_review_prompt(
            scope_text,
            supplemental_text=supplemental_text,
            available_tools=_detect_tools(),
        )
    else:
        prompt = build_find_prompt(
            scope_text,
            supplemental_text=supplemental_text,
            available_tools=_detect_tools(),
        )

    # Build codex command (read-only sandbox; full-auto; skip git repo check)
    cmd = build_cmd(
        "gpt-5",
        root,
        BuildOptions(sandbox="read-only", skip_git_repo_check=True, full_auto=True),
    )
    out_last_file: Path | None = None
    if output_final_message:
        cmd.extend(["--output-last-message", output_final_message])
    elif final_only:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            out_last_file = Path(tmp.name)
        cmd.extend(["--output-last-message", str(out_last_file)])

    if dry_run:
        # Save prompt to system temp dir and print approx token count
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        outfile = tmpdir / f"codex_prompt_specimen_{mode}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        tokens = None
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = len(enc.encode(prompt))
        print(" ".join(cmd))
        print(
            f"Detected tools: {', '.join(_detect_tools()) if _detect_tools() else '(none)'}",
        )
        print(_format_tools_table(_detect_tools()))
        print(
            f"Saved prompt: {outfile} (approx tokens: {tokens if tokens is not None else 'n/a'})",
        )
        return 0

    # Execute codex with prompt on stdin
    rc = subprocess.run(cmd, check=False, input=prompt, text=True).returncode
    if out_last_file is not None:
        print(Path(out_last_file).read_text(encoding="utf-8"))
    return rc


def main(argv: list[str] | None = None) -> int:
    # Configure structlog once per process; always configure, choose renderer by env
    # Silence stdlib logging INFO by default (keep file/JSON logs if configured elsewhere)

    # Single, centralized logging config (structlog -> stdlib; console WARNING; optional file)
    configure_logging()

    parser = argparse.ArgumentParser(
        description="adgn-llm codex properties CLI",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Check current repo for violations under a static path set\n"
            "  adgn-properties check $(pwd) 'all files under src/**' --dry-run\n\n"
            "  # Fix code on a static path set (workspace-write sandbox)\n"
            "  adgn-properties fix $(pwd) 'all files under src/**'\n\n"
            "  # Check a saved specimen by name (uses manifest.yaml)\n"
            "  adgn-properties specimen-check 2025-09-02-ducktape_wt --dry-run\n\n"
            "  # Discover only-new findings vs specimen notes\n"
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
        help="Run property scan on a saved specimen (manifest.yaml)",
        description=(
            "Resolve the specimen source+scope from manifest.yaml and run a check scan.\n"
            "- Accepts specimen name (under properties/specimens), a specimen dir, or a manifest.yaml path\n"
            "- Uses a fresh, private temp checkout/copy\n"
            "- Defaults: --full-auto and --skip-git-repo-check"
        ),
    )
    p_spec.add_argument(
        "specimen",
        nargs="?",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml",
    )
    p_spec.add_argument("--dry-run", action="store_true")
    p_spec.add_argument(
        "--json",
        action="store_true",
        help="Request JSON output from critic",
    )
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
        "--json",
        action="store_true",
        help="Request JSON output from critic",
    )
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

    # New command: lint-issue — lint exactly one issue using mini_codex + docker_exec MCP
    p_spec_lint = sub.add_parser(
        "lint-issue",
        help="Lint a single issue in a specimen (mini_codex + docker_exec)",
        description=(
            "Resolve specimen source+scope from manifest.yaml, fresh checkout/copy, and run a one-off \n"
            "mini_codex agent inside a container to lint exactly one issue against the property definitions."
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

    # New command: specimen-shell — interactive bash/sh inside the hydrated specimen container (RW mount)
    p_spec_shell = sub.add_parser(
        "specimen-shell",
        help="Open an interactive shell in a container with the hydrated specimen mounted",
        description=(
            "Hydrate specimen into a temporary workspace and open an interactive shell inside a container\n"
            "with the workspace mounted at /workspace (read-write). Container uses no network and is removed on exit."
        ),
    )
    p_spec_shell.add_argument(
        "specimen",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml",
    )
    p_spec_shell.add_argument(
        "--gitconfig",
        help="Path to a gitconfig to use for private repo fallback (shallow git)",
    )
    p_spec_shell.add_argument(
        "--image",
        help="Docker image to use (defaults to the linting image)",
    )

    args = parser.parse_args(argv)

    if args.command == "lint-issue":
        # Late import via importlib to avoid circular dependency while keeping lints happy
        mod = importlib.import_module("adgn_llm.properties.lint_issue")
        client = AsyncOpenAI()
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
        gitconfig_path = None
        if getattr(args, "gitconfig", None):
            p = Path(args.gitconfig).expanduser().resolve()
            if not p.exists():
                print(f"ERROR: --gitconfig file not found: {p}")
                return 2
            gitconfig_path = str(p)
        mode = "open" if getattr(args, "allow_general_findings", False) else "find"
        return _run_specimen(
            manifest_path,
            dry_run=args.dry_run,
            embed_paths=args.embed_paths,
            gitconfig=gitconfig_path,
            mode=mode,
            final_only=getattr(args, "final_only", False),
            output_final_message=getattr(args, "output_final_message", None),
        )

    if args.command == "specimen-discover":
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
        gitconfig_path = None
        if getattr(args, "gitconfig", None):
            p = Path(args.gitconfig).expanduser().resolve()
            if not p.exists():
                print(f"ERROR: --gitconfig file not found: {p}")
                return 2
            gitconfig_path = str(p)
        # Embed existing findings to suppress repeats
        embed_paths = []
        for name in ("covered.md", "not_covered_yet.md"):
            pth = manifest_path.parent / name
            if pth.exists():
                embed_paths.append(str(pth))
        return _run_specimen(
            manifest_path,
            dry_run=args.dry_run,
            embed_paths=embed_paths,
            gitconfig=gitconfig_path,
            mode="discover",
            final_only=getattr(args, "final_only", False),
            output_final_message=getattr(args, "output_final_message", None),
        )

    if args.command == "specimen-grade":
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
            return 2
        crit_path = Path(args.critique).expanduser().resolve()
        if not crit_path.exists():
            print(f"ERROR: critique file not found: {crit_path}")
            return 2
        gitconfig_path = None
        if getattr(args, "gitconfig", None):
            p = Path(args.gitconfig).expanduser().resolve()
            if not p.exists():
                print(f"ERROR: --gitconfig file not found: {p}")
                return 2
            gitconfig_path = str(p)
        return _run_specimen_grade(
            manifest_path,
            crit_path,
            dry_run=args.dry_run,
            final_only=getattr(args, "final_only", False),
            output_final_message=getattr(args, "output_final_message", None),
            gitconfig=gitconfig_path,
        )

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
            prompt = (
                build_open_review_prompt(args.scope, available_tools=detected_tools)
                if args.allow_general_findings
                else build_find_prompt(args.scope, available_tools=detected_tools)
            )
            cmd = build_cmd(
                args.model,
                workdir,
                BuildOptions(
                    sandbox="read-only",
                    skip_git_repo_check=args.skip_git_repo_check,
                    full_auto=args.full_auto,
                ),
            )
        else:
            prompt = build_enforce_prompt(args.scope)
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
            try:
                if "tiktoken" in globals() and tiktoken is not None:
                    enc = tiktoken.get_encoding("cl100k_base")
                    tokens = len(enc.encode(prompt))
            except Exception:
                tokens = None
            print(" ".join(cmd))
            print(
                f"Detected tools: {', '.join(_detect_tools()) if _detect_tools() else '(none)'}",
            )
            print(_format_tools_table(_detect_tools()))
            print(
                f"Saved prompt: {outfile} (approx tokens: {tokens if tokens is not None else 'n/a'})",
            )
            return 0

        # Stream to subprocess stdin
        try:
            rc = subprocess.run(cmd, check=False, input=prompt, text=True).returncode
            if out_last_file is not None:
                try:
                    print(Path(out_last_file).read_text(encoding="utf-8"))
                except Exception as e:
                    print(
                        f"[error reading final message file {out_last_file}: {e}]",
                        file=sys.stderr,
                    )
            return rc
        except KeyboardInterrupt:
            return 130
    if args.command == "specimen-shell":
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
            return 2

        gitconfig_path = None
        if args.gitconfig:
            p = Path(args.gitconfig).expanduser().resolve()
            if not p.exists():
                print(f"ERROR: --gitconfig file not found: {p}")
                return 2
            gitconfig_path = str(p)

        man = load_manifest(manifest_path)

        try:
            dclient = docker.from_env()
            # Light sanity check; will raise if daemon unavailable
            dclient.ping()
        except Exception as e:
            print(f"ERROR: Docker daemon not reachable: {e}")
            return 2

        ts = int(time.time())
        slug = manifest_path.parent.name
        mount_base = Path.home() / ".cache" / "adgn-llm" / "workspaces"
        mount_base.mkdir(parents=True, exist_ok=True)
        mount_root = mount_base / f"{slug}_{ts}"

        try:
            if mount_root.exists():
                shutil.rmtree(mount_root, ignore_errors=True)

            archive = ensure_archive_for_specimen_slug(
                man, manifest_path, Path(gitconfig_path) if gitconfig_path else None
            )

            mount_root.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive, "r:gz") as tf:
                tf.extractall(mount_root)

            entries = [p for p in mount_root.iterdir() if p.is_dir()]
            if len(entries) != 1:
                print(
                    f"Unexpected archive layout under {mount_root}; expected a single top-level directory",
                )
                return 2
            content_root = entries[0]

            name = f"adgn_spec_shell_{ts}"
            container = None
            try:
                # Ensure the image exists locally; if not, instruct how to build using our packaged Dockerfile.
                image = args.image or _DEFAULT_IMAGE
                try:
                    dclient.images.get(image)
                except docker.errors.ImageNotFound:
                    dockerfile_trav = resources.files("adgn_llm").joinpath(
                        "docker/critic.Dockerfile"
                    )
                    print("ERROR: Required Docker image not found:", image)
                    print("Build it first:")
                    print(
                        f"docker build -f {shutil.quote(dockerfile_trav)} -t {image} {shlex.quote(context_dir)}"
                    )
                    return 2

                container = dclient.containers.run(
                    image=image,
                    command=["sleep", "infinity"],
                    name=name,
                    remove=True,
                    detach=True,
                    network_mode="none",
                    volumes={str(content_root): {"bind": "/workspace", "mode": "rw"}},
                    working_dir="/workspace",
                    tty=True,
                    stdin_open=True,
                )
            except Exception as e:
                print(f"ERROR: failed to start container: {e}")
                return 2

            # Attach an interactive shell using docker CLI (subprocess) — no fallback to sh
            rc = subprocess.run(
                ["docker", "exec", "-it", name, "bash"], check=False
            ).returncode
            try:
                if container:
                    container.stop()
            except Exception:
                pass
            return rc
        finally:
            if mount_root.exists():
                shutil.rmtree(mount_root, ignore_errors=True)

    else:
        parser.error("command is required")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
