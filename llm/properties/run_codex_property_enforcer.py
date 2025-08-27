#!/usr/bin/env python3
"""
Run Codex (TypeScript codex-tui CLI) to enforce properties on changed files between merge-base and HEAD.

Usage:
  run_codex_property_enforcer.py WORKDIR [options]

Assumptions:
  - Requires the TypeScript codex-tui CLI (`codex`) in PATH (not codex-rs).

Positional arguments:
  WORKDIR               Directory Codex should use as its working root (-C)

Options:
  -m, --model MODEL     Codex model to use (default: env MODEL or 'gpt-5')
  --properties-dir DIR  Directory containing property .md files (default: <this_script_dir>/properties)
  --full-auto           Add Codex's --full-auto convenience flag
  --dry-run             Print the command and prompt but do NOT execute Codex
  --skip-git-repo-check Pass Codex's --skip-git-repo-check flag
  --upstream-ref REF    Upstream ref to compute merge-base (required)
  --copy-prompt         Copy composed prompt to clipboard (requires pyperclip)

Examples:
  ./run_codex_property_enforcer.py ~/code/worktrees/wip --upstream-ref origin/main --full-auto --dry-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
import codex_utils as cx  # Shared helpers (assumes TypeScript codex-tui 'codex')










def build_prompt(properties_dir: Path, base_sha: str) -> str:
    # Inline all property files via shared helper
    properties_text = cx.read_all_properties_text(properties_dir)

    return dedent(f"""
    Ensure all code changed in the Git diff {base_sha}..HEAD conforms to the properties defined below and refactor as needed to satisfy them without altering behavior.

    Context and constraints:
    - Scope changes to files in: git diff --name-only "{base_sha}"...HEAD
    - Apply minimal, behavior-preserving edits to satisfy all properties.
    - Prefer small, isolated edits per file.
    - Do not commit changes.
    - After edits, run existing linters/formatters if present (e.g., ruff, pre-commit) and re-verify against properties.

    Requirements:
    - You MUST check EVERY PART of the FULL Git diff
    - You MUST edit ALL files in the Git diff to comply with ALL property definition files

    Property definitions (verbatim):
    ```markdown
    {properties_text}
    ```

    Operational guidance:
    - Ask for confirmation before any destructive action (deletes/mass renames). Keep changes within the workspace.
    - If a property appears to conflict with code behavior, explain the conflict and propose the smallest safe change in your final report.

    Deliverables:
    - Apply changes directly in the workspace.
    - Print a concise change report as your final message: files changed, properties addressed per file, and any remaining violations you could not safely fix.
    """)




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
    parser.add_argument("--copy-prompt", action="store_true", help="Copy composed prompt to clipboard")
    parser.add_argument("--skip-git-repo-check", action="store_true", help="Pass Codex's --skip-git-repo-check flag")
    parser.add_argument("--upstream-ref", required=True, help="Upstream ref to compute merge-base (e.g., origin/main)")

    args = parser.parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    cx.ensure_dir(workdir)

    script_dir = Path(__file__).resolve().parent
    properties_dir = cx.resolve_properties_dir(script_dir, args.properties_dir)

    base_sha = cx.determine_merge_base(workdir, args.upstream_ref)

    prompt = build_prompt(properties_dir, base_sha)
    cmd = cx.build_codex_cmd(
        model=args.model,
        workdir=workdir,
        sandbox="workspace-write",
        skip_git_repo_check=args.skip_git_repo_check,
        full_auto=args.full_auto,
        extra_configs=['sandbox_permissions=["disk-full-read-access"]'],
    )

    def _copy_prompt(p: str) -> None:
        cx.copy_to_clipboard(p)

    print(f"Codex working dir : {workdir}")
    print(f"Properties dir    : {properties_dir}")
    print(f"Diff range        : {base_sha}...HEAD")
    print(f"Model             : {args.model}")
    print(f"Full auto         : {args.full_auto}")
    print(f"Skip repo check   : {args.skip_git_repo_check}")

    if args.copy_prompt:
        _copy_prompt(prompt)

    if args.dry_run:
        cx.print_dry_run(cmd, prompt)
        return 0

    # Execute Codex and stream output
    try:
        proc = subprocess.run(cmd, input=prompt, text=True)
        return proc.returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
