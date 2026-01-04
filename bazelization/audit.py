#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pygit2"]
# ///
"""Audit Bazelization coverage in the repository.

Compares git-tracked Python files against files actually in Bazel srcs.

Usage:
    ./bazelization/audit.py
"""

from collections import defaultdict
from pathlib import Path
import subprocess

import pygit2

REPO_ROOT = Path(__file__).parent.parent

# Intentionally not Bazelized
INTENTIONALLY_EXCLUDED = {
    "ansible",  # Ansible modules managed by Ansible
    "nix",  # Nix configs
}


def find_git_python_files() -> set[Path]:
    """Find all git-tracked Python files."""
    repo = pygit2.Repository(REPO_ROOT)
    index = repo.index
    index.read()

    files = set()
    for entry in index:
        if entry.path.endswith(".py"):
            files.add(Path(entry.path))
    return files


def find_bazel_python_sources() -> set[Path]:
    """Query Bazel for all Python files in srcs and data of py_* targets."""
    sources = set()

    for kind in ["py_library", "py_test", "py_binary"]:
        # Query for srcs
        for attr in ["srcs", "data"]:
            result = subprocess.run(
                ["bazel", "query", f'labels({attr}, kind("{kind}", //...))'],
                check=False,
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            )
            if result.returncode != 0:
                continue

            for line in result.stdout.strip().split("\n"):
                if not line or not line.endswith(".py"):
                    continue
                # Convert //pkg:path/to/file.py to pkg/path/to/file.py
                label = line.removeprefix("//")
                if ":" in label:
                    pkg, file = label.split(":", 1)
                    if pkg:
                        sources.add(Path(pkg) / file)
                    else:
                        sources.add(Path(file))
                else:
                    sources.add(Path(label))

    return sources


def query_bazel_targets(kind: str) -> list[str]:
    """Query Bazel for targets of a specific kind."""
    result = subprocess.run(
        ["bazel", "query", f'kind("{kind}", //...)'], check=False, capture_output=True, text=True, cwd=REPO_ROOT
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().split("\n") if line]


def query_manual_targets() -> list[str]:
    """Query Bazel for targets tagged as manual."""
    result = subprocess.run(
        ["bazel", "query", 'attr(tags, "manual", //...)'], check=False, capture_output=True, text=True, cwd=REPO_ROOT
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().split("\n") if line]


def analyze() -> None:
    print("Scanning git repository...")
    git_files = find_git_python_files()

    print("Querying Bazel for Python srcs...")
    bazel_files = find_bazel_python_sources()

    # Categorize files
    covered = []
    uncovered: dict[str, list[Path]] = defaultdict(list)
    intentional: dict[str, list[Path]] = defaultdict(list)

    for rel in sorted(git_files):
        top_dir = rel.parts[0] if rel.parts else ""

        if top_dir in INTENTIONALLY_EXCLUDED:
            intentional[top_dir].append(rel)
        elif rel in bazel_files:
            covered.append(rel)
        else:
            uncovered[top_dir].append(rel)

    # Query Bazel for target counts
    print("Querying Bazel targets...")
    py_libraries = query_bazel_targets("py_library")
    py_tests = query_bazel_targets("py_test")
    ruff_tests = query_bazel_targets("ruff_test")
    manual_targets = query_manual_targets()

    total_git = len(git_files)
    total_intentional = sum(len(v) for v in intentional.values())
    total_uncovered = sum(len(v) for v in uncovered.values())

    print()
    print("=" * 60)
    print("BAZELIZATION COVERAGE REPORT")
    print("=" * 60)
    print()
    print(f"Python files (git-tracked): {total_git}")
    print(f"In Bazel py_* srcs:         {len(covered)}")
    print(f"Not in any target:          {total_uncovered}")
    print(f"Intentionally excluded:     {total_intentional}")
    if total_git - total_intentional > 0:
        pct = len(covered) / (total_git - total_intentional) * 100
        print(f"Coverage:                   {pct:.1f}%")
    print()

    print("=" * 60)
    print("BAZEL TARGETS")
    print("=" * 60)
    print(f"py_library: {len(py_libraries)}")
    print(f"py_test:    {len(py_tests)}")
    print(f"ruff_test:  {len(ruff_tests)}")
    print()

    if manual_targets:
        print("Manual targets (excluded from bazel test //...):")
        for target in sorted(manual_targets):
            if not target.startswith("//:"):  # Skip root requirements targets
                print(f"  {target}")
        print()

    if uncovered:
        print("=" * 60)
        print("NOT IN ANY BAZEL TARGET")
        print("=" * 60)
        for dir_name, files in sorted(uncovered.items()):
            print(f"\n{dir_name}/ ({len(files)} files)")
            for f in sorted(files)[:10]:
                print(f"  - {f}")
            if len(files) > 10:
                print(f"  ... and {len(files) - 10} more")
        print()

    print("=" * 60)
    print("INTENTIONALLY EXCLUDED")
    print("=" * 60)
    for dir_name, files in sorted(intentional.items()):
        print(f"  {dir_name}/ ({len(files)} files)")


if __name__ == "__main__":
    analyze()
