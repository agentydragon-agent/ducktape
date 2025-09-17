from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Literal

from openai import AsyncOpenAI
import tiktoken

from adgn.llm.logging_config import configure_logging
from adgn.llm.properties.agent_runner import run_prompt_async
from adgn.llm.properties.critic import CriticSubmitPayload
from adgn.llm.properties.docker_env import properties_docker_spec
from adgn.llm.properties.grade_runner import _metrics_row, grade_critic_output
from adgn.llm.properties.models.issue import IssueCore, LineRange, Occurrence
from adgn.llm.properties.prompts.builder import build_enforce_prompt, build_role_prompt
from adgn.llm.properties.prompts.util import build_input_schemas_json
from adgn.llm.properties.specimens.registry import (
    find_specimens_base,
    list_specimen_names,
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
        prompt,
        model,
        specs,
        client=client,
        capture_transcript=not final_only,
    )
    if output_final_message:
        Path(output_final_message).write_text(res.final_text, encoding="utf-8")
    if not final_only and res.final_text:
        print(res.final_text)
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

    args = parser.parse_args(argv)

    if args.command == "specimen-grade":
        base = find_specimens_base()
        names = list_specimen_names(base)
        slug = getattr(args, "specimen", None)
        if not slug or slug not in names:
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

        # Run grader via shared grade_runner
        async def _run() -> int:
            out_dir = Path.cwd() / "runs" / "specimen-grade" / slug
            out_dir.mkdir(parents=True, exist_ok=True)
            grade = await grade_critic_output(
                slug,
                critique,
                client,
                transcript_out_dir=out_dir,
            )
            # Print concise metrics including fuzzy values
            row = _metrics_row(grade, specimen=slug)
            print(json.dumps(row, indent=2))
            # Persist to runs/specimen-grade/<ts>
            out_path = Path.cwd() / "runs" / "specimen-grade" / f"{slug}.grade.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(grade.model_dump_json(), encoding="utf-8")
            return 0

        return asyncio.run(_run())
    if args.command in ("check", "fix"):
        workdir = Path(args.workdir).resolve()
        detected_tools = _detect_tools()
        if not getattr(args, "output_final_message", None):
            print(
                f"Detected tools    : {', '.join(detected_tools) if detected_tools else '(none)'}",
            )
            print(_format_tools_table(detected_tools))
        out_last_file: Path | None = None
        wiring = properties_docker_spec(workdir, mount_properties=True)
        if args.command == "check":
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
                ),
            )
        schemas_json = build_input_schemas_json([Occurrence, LineRange, IssueCore])
        prompt = build_enforce_prompt(
            args.scope,
            wiring=wiring,
            schemas_json=schemas_json,
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
    parser.error("command is required")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
