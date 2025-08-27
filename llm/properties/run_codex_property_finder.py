#!/usr/bin/env python3
"""
Run Codex (TypeScript codex-tui CLI) to analyze (find-only) property violations on changed files between merge-base and HEAD, or optionally a single file.

Usage:
  run_codex_property_finder.py WORKDIR --upstream-ref ORIGIN/BRANCH [options]

Assumptions:
  - Requires the TypeScript codex-tui CLI (`codex`) in PATH (not codex-rs).

Positional arguments:
  WORKDIR               Directory Codex should use as its working root (-C)

Options:
  -m, --model MODEL     Codex model to use (default: env MODEL or 'gpt-5')
  --properties-dir DIR  Directory containing property .md files (default: <this_script_dir>/properties)
  --file PATH           Analyze only this file (relative to WORKDIR or absolute); do not edit
  --dry-run             Print the command and prompt but do NOT execute Codex
  --skip-git-repo-check Pass Codex's --skip-git-repo-check flag
  --full-auto           Add Codex's --full-auto flag (kept for parity)
  --copy-prompt         Copy composed prompt to clipboard (requires pyperclip)
  --upstream-ref REF    Upstream ref to compute merge-base (e.g., origin/main) [required]

Output:
  Structured textual report listing suspected violations per property and per file.
  This script never edits files (read-only sandbox).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import codex_utils as cx


def build_prompt(properties_dir: Path, base_sha: str, file_arg: str | None) -> str:
    # Inline all property definitions
    properties_text = cx.read_all_properties_text(properties_dir)

    target_scope = (
        f"Limit analysis to file: {file_arg} (but you may inspect history and diffs for context)."
        if file_arg
        else "Analyze all files changed in the Git diff range."
    )

    return dedent(f"""
    Analyze the codebase for violations of the properties defined below. Do not modify any files. Produce a structured textual report.

    Scope:
    - Diff range: {base_sha}..HEAD
    - {target_scope}

    Constraints:
    - Read-only sandbox: do not execute commands that modify files or the repo
    - You MAY run read-only commands to inspect context (e.g., `git status`, `git diff --unified=0`)
    - You MUST check every changed hunk within scope

    Reporting requirements:
    - Group by file, then by property title
    - For each violation: include short rationale and line references (from `git diff --unified=0` or file line numbers)
    - If no violations for a file, explicitly state "No violations"

    Property definitions (verbatim):
    ```markdown
    {properties_text}
    ```
    """)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Find (do not fix) violations of properties using Codex (TypeScript codex-tui) in a Git workdir or a single file",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("workdir", metavar="WORKDIR", help="Directory Codex should use as its working root (-C)")
    parser.add_argument("--upstream-ref", required=True, help="Upstream ref to compute merge-base (e.g., origin/main)")
    parser.add_argument("-m", "--model", default=os.environ.get("MODEL", "gpt-5"), help="Codex model")
    parser.add_argument("--properties-dir", help="Directory containing property .md files; default is <script_dir>/properties")
    parser.add_argument("--file", help="Analyze only this file (relative to WORKDIR or absolute)")
    parser.add_argument("--dry-run", action="store_true", help="Print the command and prompt but do NOT execute Codex")
    parser.add_argument("--skip-git-repo-check", action="store_true", help="Pass Codex's --skip-git-repo-check flag")
    parser.add_argument("--full-auto", action="store_true", help="Add Codex's --full-auto flag")
    parser.add_argument("--copy-prompt", action="store_true", help="Copy composed prompt to clipboard")

    args = parser.parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    cx.ensure_dir(workdir)

    script_dir = Path(__file__).resolve().parent
    properties_dir = cx.resolve_properties_dir(script_dir, args.properties_dir)

    base_sha = cx.determine_merge_base(workdir, args.upstream_ref)

    file_arg = args.file
    if file_arg:
        file_path = Path(file_arg).expanduser()
        if not file_path.is_absolute():
            file_path = (workdir / file_path).resolve()
        file_arg = str(file_path)

    prompt = build_prompt(properties_dir, base_sha, file_arg)
    cmd = cx.build_codex_cmd(
        model=args.model,
        workdir=workdir,
        sandbox="read-only",
    )

    if args.copy_prompt:
        cx.copy_to_clipboard(prompt)

    print(f"Codex working dir : {workdir}")
    print(f"Properties dir    : {properties_dir}")
    print(f"Diff range        : {base_sha}...HEAD")
    if file_arg:
        print(f"Single file       : {file_arg}")
    print(f"Model             : {args.model}")

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
