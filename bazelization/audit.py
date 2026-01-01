#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pygit2"]
# ///
"""Audit Bazelization coverage in the repository.

Run this script periodically to track Bazelization progress and identify gaps.

Usage:
    ./bazelization/audit.py
    # or
    uv run bazelization/audit.py
"""

import subprocess
from collections import defaultdict
from pathlib import Path

import pygit2

REPO_ROOT = Path(__file__).parent.parent

# Intentionally not Bazelized
INTENTIONALLY_EXCLUDED = {
    "ansible",  # Ansible modules managed by Ansible
    "nix",  # Nix configs
}


def find_python_files() -> list[Path]:
    """Find all git-tracked Python files."""
    repo = pygit2.Repository(REPO_ROOT)
    index = repo.index
    index.read()

    files = []
    for entry in index:
        if entry.path.endswith(".py"):
            files.append(REPO_ROOT / entry.path)
    return files


def find_build_dirs() -> set[Path]:
    """Find directories containing BUILD.bazel or BUILD files via git."""
    repo = pygit2.Repository(REPO_ROOT)
    index = repo.index
    index.read()

    builds = set()
    for entry in index:
        if entry.path.endswith("BUILD.bazel") or entry.path.endswith("/BUILD") or entry.path == "BUILD":
            builds.add((REPO_ROOT / entry.path).parent)
    return builds


def query_bazel_targets(kind: str) -> list[str]:
    """Query Bazel for targets of a specific kind."""
    result = subprocess.run(
        ["bazel", "query", f'kind("{kind}", //...)'],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().split("\n") if line]


def query_manual_targets() -> list[str]:
    """Query Bazel for targets tagged as manual."""
    result = subprocess.run(
        ["bazel", "query", 'attr(tags, "manual", //...)'],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().split("\n") if line]


def get_package_for_file(py_file: Path, build_dirs: set[Path]) -> Path | None:
    """Find the BUILD file directory that covers this Python file."""
    current = py_file.parent
    while current != REPO_ROOT.parent:
        if current in build_dirs:
            return current
        current = current.parent
    return None


def analyze() -> None:
    print("Scanning repository...")
    py_files = find_python_files()
    build_dirs = find_build_dirs()

    covered = []
    uncovered: dict[str, list[Path]] = defaultdict(list)
    intentional: dict[str, list[Path]] = defaultdict(list)

    for py_file in py_files:
        rel = py_file.relative_to(REPO_ROOT)
        pkg = get_package_for_file(py_file, build_dirs)

        # Check if intentionally excluded
        top_dir = rel.parts[0] if rel.parts else ""
        if top_dir in INTENTIONALLY_EXCLUDED:
            intentional[top_dir].append(rel)
        elif pkg:
            covered.append(rel)
        else:
            # Group by top-level directory
            uncovered[top_dir].append(rel)

    # Query Bazel for target counts
    print("Querying Bazel targets...")
    py_libraries = query_bazel_targets("py_library")
    py_tests = query_bazel_targets("py_test")
    ruff_tests = query_bazel_targets("ruff_test")
    manual_targets = query_manual_targets()

    print()
    print("=" * 60)
    print("BAZELIZATION COVERAGE REPORT")
    print("=" * 60)
    print()
    print(f"Python files (git-tracked): {len(py_files)}")
    print(f"Covered by BUILD:           {len(covered)}")
    print(f"Not covered:                {sum(len(v) for v in uncovered.values())}")
    print(f"Intentionally excluded:     {sum(len(v) for v in intentional.values())}")
    if py_files:
        pct = len(covered) / len(py_files) * 100
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
        print("UNCOVERED DIRECTORIES")
        print("=" * 60)
        for dir_name, files in sorted(uncovered.items()):
            print(f"\n{dir_name}/ ({len(files)} files)")
            for f in sorted(files)[:5]:
                print(f"  - {f}")
            if len(files) > 5:
                print(f"  ... and {len(files) - 5} more")
        print()

    print("=" * 60)
    print("INTENTIONALLY EXCLUDED")
    print("=" * 60)
    for dir_name, files in sorted(intentional.items()):
        print(f"  {dir_name}/ ({len(files)} files)")

    print()
    print("=" * 60)
    print(f"BUILD FILES: {len(build_dirs)} directories")
    print("=" * 60)
    for bd in sorted(build_dirs):
        print(f"  {bd.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    analyze()
