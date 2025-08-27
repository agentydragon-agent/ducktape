#!/usr/bin/env python3
"""
Codex properties checker: unified CLI with subcommands `find` and `enforce`.

- find: Analyze for property violations without modifying files (read-only sandbox)
- enforce: Apply minimal changes to satisfy properties (workspace-write sandbox)

Scope is provided as a single freeform description (diff range and/or file list).

Assumptions:
- Requires the TypeScript codex-tui CLI (`codex`) in PATH (not codex-rs).

Usage examples:
  # Find violations in a diff range description
  codex_checker.py find ~/repo "src/foo/bar.py and src/baz.py between merge-base with master and 2 commits before HEAD"

  # Enforce properties on files changed since a tag
  codex_checker.py enforce ~/repo "all files changed since tag v1.2.0"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import codex_utils as cx


def build_find_prompt(properties_dir: Path, scope_text: str) -> str:
    properties_text = cx.read_all_properties_text(properties_dir)

    return dedent(
        f"""
        Analyze the codebase for violations of the properties defined below. Do not modify any files. Produce a structured textual report.

        Scope (freeform):
        - {scope_text}

        Scope interpretation rules:
        - The scope may describe either:
          1) a Git diff range (e.g., "between merge-base with master and 2 commits before HEAD"), or
          2) a static set of files/paths
        - If it's a diff description: resolve to a concrete diff range, enumerate files and hunks, and use `git diff --unified=0` for references.
        - If it's a static file set: analyze only those files.
        - On ambiguity, choose the most conservative interpretation, state the resolved scope, and do not include anything outside it.

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
        """,
    )


def build_enforce_prompt(properties_dir: Path, scope_text: str) -> str:
    properties_text = cx.read_all_properties_text(properties_dir)

    return dedent(
        f"""
        Ensure code within the described scope conforms to the properties defined below and refactor as needed to satisfy them without altering behavior.

        Scope (freeform):
        - {scope_text}

        Scope interpretation rules:
        - The scope may describe either:
          1) a Git diff range (e.g., "between merge-base with master and 2 commits before HEAD"), or
          2) a static set of files/paths
        - If it's a diff description: resolve to a concrete diff range, enumerate files and hunks, and use `git diff --unified=0` for references.
        - If it's a static file set: edit only those files.
        - On ambiguity, choose the most conservative interpretation, state the resolved scope, and avoid touching anything outside it unless required by the editing policy below.

        Editing policy:
        - Prefer minimal, localized edits within the scoped hunks/sections.
        - You MAY edit outside the scoped hunks/sections ONLY when necessary to bring the scoped changes and any code you touched into full compliance with all properties (e.g., moving imports to the top of file).
        - If such edits cascade (A requires B, which requires C, ...), keep fixing until everything you changed and everything originally in scope is compliant, then stop.
        - Do NOT perform broad or unrelated refactors beyond what is required for compliance.
        - Do not commit changes.
        - After edits, run existing linters/formatters if present (e.g., ruff, pre-commit) and re-verify against properties.

        Requirements:
        - You MUST check every changed hunk within the resolved scope
        - You MUST bring all scoped files/sections and any cascaded edits into compliance with ALL property definition files

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
        """,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Codex properties checker (find/enforce) using a freeform scope description",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "workdir",
        metavar="WORKDIR",
        help="Directory Codex should use as its working root (-C)",
    )
    common.add_argument(
        "-m",
        "--model",
        default=os.environ.get("MODEL", "gpt-5"),
        help="Codex model",
    )
    common.add_argument(
        "--properties-dir",
        help="Directory containing property .md files; default is <script_dir>/properties",
    )
    common.add_argument(
        "scope",
        help="Freeform description of diff range and/or files to analyze/edit",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command and prompt but do NOT execute Codex",
    )
    common.add_argument(
        "--skip-git-repo-check",
        action="store_true",
        help="Pass Codex's --skip-git-repo-check flag",
    )
    common.add_argument(
        "--full-auto",
        action="store_true",
        help="Add Codex's --full-auto flag",
    )
    common.add_argument(
        "--copy-prompt",
        action="store_true",
        help="Copy composed prompt to clipboard",
    )

    # find
    subparsers.add_parser(
        "find",
        parents=[common],
        help="Analyze property violations (read-only)",
    )

    # enforce
    subparsers.add_parser(
        "enforce",
        parents=[common],
        help="Enforce properties with minimal edits (workspace-write)",
    )

    # fix (alias for enforce)
    subparsers.add_parser(
        "fix",
        parents=[common],
        help="Alias for 'enforce' (workspace-write)",
    )

    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    workdir = Path(args.workdir).expanduser().resolve()
    cx.ensure_dir(workdir)

    script_dir = Path(__file__).resolve().parent
    properties_dir = cx.resolve_properties_dir(script_dir, args.properties_dir)

    if args.command == "find":
        prompt = build_find_prompt(properties_dir, args.scope)
        cmd = cx.build_codex_cmd(
            model=args.model,
            workdir=workdir,
            sandbox="read-only",
            skip_git_repo_check=args.skip_git_repo_check,
            full_auto=args.full_auto,
        )
    elif args.command in ("enforce", "fix"):
        prompt = build_enforce_prompt(properties_dir, args.scope)
        cmd = cx.build_codex_cmd(
            model=args.model,
            workdir=workdir,
            sandbox="workspace-write",
            skip_git_repo_check=args.skip_git_repo_check,
            full_auto=args.full_auto,
            extra_configs=['sandbox_permissions=["disk-full-read-access"]'],
        )
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 2

    # Optional: copy prompt
    if args.copy_prompt:
        cx.copy_to_clipboard(prompt)

    # Info summary
    print(f"Codex working dir : {workdir}")
    print(f"Properties dir    : {properties_dir}")
    print(f"Scope (freeform)  : {args.scope}")
    print(f"Mode              : {args.command}")
    print(f"Model             : {args.model}")
    if hasattr(args, "full_auto"):
        print(f"Full auto         : {args.full_auto}")
    if hasattr(args, "skip_git_repo_check"):
        print(f"Skip repo check   : {args.skip_git_repo_check}")

    if args.dry_run:
        cx.print_dry_run(cmd, prompt)
        return 0

    try:
        proc = subprocess.run(cmd, check=False, input=prompt, text=True)
        return proc.returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
