#!/usr/bin/env python3
"""Unified formatter that routes files to appropriate formatters.

Unlike rules_lint's format.sh, this handles filenames with special characters correctly
by not using `find` (which breaks on filenames like "-recipe-").

Exclusions: Files with these .gitattributes are skipped (like rules_lint):
    - linguist-generated=true
    - gitlab-generated=true
    - rules-lint-ignored=true

Usage:
    bazel run //tools/format -- file1.py file2.js  # Format specific files
    bazel run //tools/format                        # Format all tracked files
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Resolve runfiles paths
from python.runfiles import runfiles

_RUNFILES_OPT = runfiles.Create()
if _RUNFILES_OPT is None:
    raise RuntimeError("Could not create runfiles")
_RUNFILES: runfiles.Runfiles = _RUNFILES_OPT

# Extension -> formatter mapping
EXTENSION_MAP: dict[str, str] = {
    # Prettier
    ".js": "prettier",
    ".jsx": "prettier",
    ".ts": "prettier",
    ".tsx": "prettier",
    ".css": "prettier",
    ".html": "prettier",
    ".md": "prettier",
    ".json": "prettier",
    ".yaml": "prettier",
    ".yml": "prettier",
    # Ruff
    ".py": "ruff",
    # Shell
    ".sh": "shfmt",
    ".bash": "shfmt",
    # Starlark
    ".bzl": "buildifier",
    ".bazel": "buildifier",
}

# Exact filename -> formatter
FILENAME_MAP: dict[str, str] = {
    "BUILD": "buildifier",
    "BUILD.bazel": "buildifier",
    "WORKSPACE": "buildifier",
    "WORKSPACE.bazel": "buildifier",
}


def get_formatter(path: Path) -> str | None:
    """Determine which formatter to use for a file."""
    if path.name in FILENAME_MAP:
        return FILENAME_MAP[path.name]
    return EXTENSION_MAP.get(path.suffix.lower())


def get_all_files() -> list[Path]:
    """Get all tracked/modified files via git ls-files."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--modified", "--other", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(f) for f in result.stdout.strip().split("\n") if f]


# Attributes that mark a file as ignored (matching rules_lint behavior)
IGNORE_ATTRIBUTES = ("linguist-generated", "gitlab-generated", "rules-lint-ignored")


def filter_ignored(files: list[Path]) -> list[Path]:
    """Filter out files marked as ignored via .gitattributes."""
    if not files:
        return []

    # Batch check all attributes for all files in one call
    result = subprocess.run(
        ["git", "check-attr", *IGNORE_ATTRIBUTES, "--", *[str(f) for f in files]],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # If git check-attr fails, don't filter anything
        return files

    # Parse output: "path: attr: value" format
    # A file is ignored if any attribute is "true" (not "unspecified" or "false")
    ignored_files: set[str] = set()
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        # Format: "path: attribute: value"
        parts = line.split(": ", 2)
        if len(parts) == 3 and parts[2] == "true":
            ignored_files.add(parts[0])

    return [f for f in files if str(f) not in ignored_files]


def run_formatter(formatter: str, files: list[Path], check_mode: bool) -> bool:
    """Run a formatter on files. Returns True if successful."""
    if not files:
        return True

    # Filter to existing files
    existing = [str(f) for f in files if f.exists()]
    if not existing:
        return True

    # Get binary path from environment (set by Bazel) and resolve via runfiles
    bin_var = f"{formatter.upper()}_BIN"
    rlocation_path = os.environ.get(bin_var)
    if not rlocation_path:
        print(f"Error: {bin_var} not set", file=sys.stderr)
        return False

    bin_path = _RUNFILES.Rlocation(rlocation_path)
    if not bin_path or not Path(bin_path).exists():
        print(f"Error: could not resolve {rlocation_path}", file=sys.stderr)
        return False

    # Build command based on formatter
    if formatter == "prettier":
        cmd = [bin_path, "--check" if check_mode else "--write", *existing]
    elif formatter == "ruff":
        cmd = [bin_path, "format", *(["--check"] if check_mode else []), *existing]
    elif formatter == "shfmt":
        cmd = [bin_path, "-d" if check_mode else "-w", *existing]
    elif formatter == "buildifier":
        # buildifier.check is a different binary for check mode
        cmd = [bin_path, *existing]
    else:
        print(f"Unknown formatter: {formatter}", file=sys.stderr)
        return False

    print(f"Formatting {len(existing)} files with {formatter}...")
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def main() -> int:
    check_mode = os.environ.get("FMT_CHECK", "").lower() in ("1", "true", "yes")

    # Change to workspace directory if set
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace:
        os.chdir(workspace)

    # Get files to format
    files = [Path(f) for f in sys.argv[1:]] if len(sys.argv) > 1 else get_all_files()

    # Filter out files marked as ignored via .gitattributes
    files = filter_ignored(files)

    # Group by formatter
    by_formatter: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        formatter = get_formatter(f)
        if formatter:
            by_formatter[formatter].append(f)

    # Run formatters
    success = True
    for formatter, formatter_files in by_formatter.items():
        if not run_formatter(formatter, formatter_files, check_mode):
            success = False

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
