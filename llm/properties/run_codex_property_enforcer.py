#!/usr/bin/env python3
"""
Run Codex to enforce properties on changed files between merge-base and HEAD.

Usage:
  python run_codex_property_enforcer.py WORKDIR [options]

Positional arguments:
  WORKDIR               Directory Codex should use as its working root (-C)

Options:
  -m, --model MODEL     Codex model to use (default: env MODEL or 'gpt-5')
  --properties-dir DIR  Directory containing property .md files (default: <this_script_dir>/properties)
  --full-auto           Add Codex's --full-auto convenience flag
  --dry-run             Print the command and prompt but do NOT execute Codex
  --skip-git-repo-check Pass Codex's --skip-git-repo-check flag
  --upstream-ref REF    Upstream ref to compute merge-base (required)

Examples:
  ./run_codex_property_enforcer.py ~/code/worktrees/wip --full-auto --dry-run
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


def resolve_properties_dir(default_base: Path, override: str | None) -> Path:
    if override:
        p = Path(override).expanduser().resolve()
    else:
        p = (default_base / "properties").resolve()
    if not p.is_dir():
        raise SystemExit(f"Error: properties directory not found: {p}")
    return p


def ensure_dir(path: Path) -> None:
    if not path.is_dir():
        raise SystemExit(f"Error: WORKDIR does not exist or is not a directory: {path}")


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True)


def determine_merge_base(workdir: Path, upstream_ref: str | None) -> str:
    if not upstream_ref:
        raise SystemExit("Error: --upstream-ref is required (e.g., origin/main)")
    cp = git("merge-base", upstream_ref, "HEAD", cwd=workdir)
    if cp.returncode == 0 and cp.stdout.strip():
        return cp.stdout.strip()
    raise SystemExit(f"Error: could not determine merge base against {upstream_ref}. Ensure the ref exists and is fetched.")


def build_prompt(properties_dir: Path, base_sha: str) -> str:
    # Instructions sent to Codex via stdin
    return dedent(f"""
    Ensure all code changed in the Git diff {base_sha}..HEAD conforms to the properties in {properties_dir}/*.md and refactor as needed to satisfy them without altering behavior.

    Context and constraints:
    - Scope changes to files in: git diff --name-only "{base_sha}"...HEAD
    - Read all property files under {properties_dir}/*.md and treat them as enforcement rules.
    - Apply minimal, behavior-preserving edits to satisfy all properties.
    - Prefer small, isolated edits per file.
    - Do not commit changes.
    - After edits, run existing linters/formatters if present (e.g., ruff, pre-commit) and re-verify against properties.

    Requirements:
    - You MUST check EVERY PART of the FULL Git diff
    - You MUST edit ALL files in the Git diff to comply with ALL property definition files

    Operational guidance:
    - Ask for confirmation before any destructive action (deletes/mass renames). Keep changes within the workspace.
    - If a property appears to conflict with code behavior, explain the conflict and propose the smallest safe change in your final report.

    Deliverables:
    - Apply changes directly in the workspace.
    - Print a concise change report as your final message: files changed, properties addressed per file, and any remaining violations you could not safely fix.
    """)


def build_codex_cmd(model: str, workdir: Path, full_auto: bool, skip_git_repo_check: bool) -> list[str]:
    cmd = [
        "codex",
        "exec",
        "-m",
        model,
        "-s",
        "workspace-write",
        "-C",
        str(workdir),
        "-c",
        'sandbox_permissions=["disk-full-read-access"]',
    ]
    if full_auto:
        cmd.append("--full-auto")
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    return cmd


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run Codex to enforce llm/properties on changes in a Git workdir",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("workdir", metavar="WORKDIR", help="Directory Codex should use as its working root (-C)")
    parser.add_argument("-m", "--model", default=os.environ.get("MODEL", "gpt-5"), help="Codex model")
    parser.add_argument("--properties-dir", help="Directory containing property .md files; default is <script_dir>/properties")
    parser.add_argument("--full-auto", action="store_true", help="Add Codex's --full-auto flag")
    parser.add_argument("--dry-run", action="store_true", help="Print the command and prompt but do NOT execute Codex")
    parser.add_argument("--skip-git-repo-check", action="store_true", help="Pass Codex's --skip-git-repo-check flag")
    parser.add_argument("--upstream-ref", required=True, help="Upstream ref to compute merge-base (e.g., origin/main)")

    args = parser.parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    ensure_dir(workdir)

    script_dir = Path(__file__).resolve().parent
    properties_dir = resolve_properties_dir(script_dir, args.properties_dir)

    if shutil.which("codex") is None:
        raise SystemExit("Error: 'codex' CLI not found in PATH")

    base_sha = determine_merge_base(workdir, args.upstream_ref)

    prompt = build_prompt(properties_dir, base_sha)
    cmd = build_codex_cmd(args.model, workdir, args.full_auto, args.skip_git_repo_check)

    print(f"Codex working dir : {workdir}")
    print(f"Properties dir    : {properties_dir}")
    print(f"Diff range        : {base_sha}...HEAD")
    print(f"Model             : {args.model}")
    print(f"Full auto         : {args.full_auto}")
    print(f"Skip repo check   : {args.skip_git_repo_check}")

    if args.dry_run:
        print("\n# Dry run: would execute command:\n" + " ".join(map(str, cmd)))
        print("\n# Prompt (full):\n")
        print(prompt)
        return 0

    # Execute Codex and stream output
    try:
        proc = subprocess.run(cmd, input=prompt, text=True)
        return proc.returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
