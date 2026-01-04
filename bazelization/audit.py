#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pygit2"]
# ///
"""Audit Bazelization coverage in the repository.

Compares git-tracked source files against files in Bazel targets.

Usage:
    ./bazelization/audit.py
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import subprocess

import pygit2

REPO_ROOT = Path(__file__).parent.parent

# Intentionally not Bazelized
INTENTIONALLY_EXCLUDED = {
    "ansible",  # Ansible modules managed by Ansible
    "nix",  # Nix configs
}


@dataclass
class LanguageConfig:
    """Configuration for tracking a specific language."""

    name: str
    extensions: list[str]
    bazel_kinds: list[str]
    bazel_attrs: list[str] = None

    def __post_init__(self):
        if self.bazel_attrs is None:
            self.bazel_attrs = ["srcs", "data"]


# Languages to track
LANGUAGES = [
    LanguageConfig(name="Python", extensions=[".py"], bazel_kinds=["py_library", "py_test", "py_binary"]),
    LanguageConfig(name="TypeScript", extensions=[".ts"], bazel_kinds=["ts_library", "ts_project"]),
    LanguageConfig(
        name="JavaScript", extensions=[".js"], bazel_kinds=["js_library", "js_binary", "js_run_binary"]
    ),
    LanguageConfig(name="Rust", extensions=[".rs"], bazel_kinds=["rust_library", "rust_binary", "rust_test"]),
    LanguageConfig(name="Shell", extensions=[".sh"], bazel_kinds=["sh_library", "sh_binary", "sh_test"]),
]


def find_git_files_by_extensions(extensions: list[str]) -> set[Path]:
    """Find all git-tracked files matching the given extensions."""
    repo = pygit2.Repository(REPO_ROOT)
    index = repo.index
    index.read()

    files = set()
    for entry in index:
        if any(entry.path.endswith(ext) for ext in extensions):
            files.add(Path(entry.path))
    return files


def find_all_git_files() -> set[Path]:
    """Find all git-tracked files."""
    repo = pygit2.Repository(REPO_ROOT)
    index = repo.index
    index.read()

    files = set()
    for entry in index:
        files.add(Path(entry.path))
    return files


def find_bazel_sources_by_extension(extensions: list[str], kinds: list[str], attrs: list[str]) -> set[Path]:
    """Query Bazel for files matching extensions in specified target kinds and attributes."""
    sources = set()

    for kind in kinds:
        for attr in attrs:
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
                if not line:
                    continue
                if not any(line.endswith(ext) for ext in extensions):
                    continue

                # Convert //pkg:path/to/file.ext to pkg/path/to/file.ext
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


def find_all_bazel_inputs() -> set[Path]:
    """Find all files that are inputs to any Bazel target (srcs, data, deps transitively)."""
    result = subprocess.run(
        ["bazel", "query", "labels(srcs, //...) + labels(data, //...)"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        return set()

    inputs = set()
    for line in result.stdout.strip().split("\n"):
        if not line or line.startswith("//") and ":" not in line:
            # Skip targets without files
            continue

        # Convert //pkg:path/to/file to pkg/path/to/file
        label = line.removeprefix("//")
        if ":" in label:
            pkg, file = label.split(":", 1)
            if pkg:
                path = Path(pkg) / file
            else:
                path = Path(file)

            # Only add if it looks like a file (not a target label)
            if path.suffix or not file.startswith("_"):
                inputs.add(path)

    return inputs


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
    print("=" * 80)
    print("BAZELIZATION COVERAGE AUDIT")
    print("=" * 80)
    print()

    # Track per-language coverage
    language_results = {}

    for lang_config in LANGUAGES:
        print(f"Scanning {lang_config.name} files...")
        git_files = find_git_files_by_extensions(lang_config.extensions)
        bazel_files = find_bazel_sources_by_extension(
            lang_config.extensions, lang_config.bazel_kinds, lang_config.bazel_attrs
        )

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

        language_results[lang_config.name] = {
            "config": lang_config,
            "git_files": git_files,
            "bazel_files": bazel_files,
            "covered": covered,
            "uncovered": uncovered,
            "intentional": intentional,
        }

    # Find files in git but not in any Bazel target at all
    print("Scanning all Bazel inputs...")
    all_git_files = find_all_git_files()
    all_bazel_inputs = find_all_bazel_inputs()

    # Files tracked by language-specific scans
    all_language_tracked = set()
    for result in language_results.values():
        all_language_tracked.update(result["git_files"])

    # Files in git but not in any Bazel target and not tracked by language scans
    git_not_in_bazel = all_git_files - all_bazel_inputs
    git_not_tracked = git_not_in_bazel - all_language_tracked

    # Categorize untracked files
    untracked_by_dir: dict[str, list[Path]] = defaultdict(list)
    untracked_intentional: dict[str, list[Path]] = defaultdict(list)

    for rel in sorted(git_not_tracked):
        top_dir = rel.parts[0] if rel.parts else ""
        if top_dir in INTENTIONALLY_EXCLUDED:
            untracked_intentional[top_dir].append(rel)
        else:
            untracked_by_dir[top_dir].append(rel)

    # Query Bazel for target counts
    print("Querying Bazel targets...")
    py_libraries = query_bazel_targets("py_library")
    py_tests = query_bazel_targets("py_test")
    ruff_tests = query_bazel_targets("ruff_test")
    manual_targets = query_manual_targets()

    # Print results
    print()
    print("=" * 80)
    print("LANGUAGE-SPECIFIC COVERAGE")
    print("=" * 80)
    print()

    for lang_name, result in language_results.items():
        total_git = len(result["git_files"])
        total_intentional = sum(len(v) for v in result["intentional"].values())
        total_uncovered = sum(len(v) for v in result["uncovered"].values())
        total_covered = len(result["covered"])

        if total_git == 0:
            continue

        print(f"{lang_name}:")
        print(f"  Git-tracked files:      {total_git}")
        print(f"  In Bazel targets:       {total_covered}")
        print(f"  Not in targets:         {total_uncovered}")
        print(f"  Intentionally excluded: {total_intentional}")
        if total_git - total_intentional > 0:
            pct = total_covered / (total_git - total_intentional) * 100
            print(f"  Coverage:               {pct:.1f}%")
        print()

    print("=" * 80)
    print("BAZEL TARGETS")
    print("=" * 80)
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

    # Print per-language uncovered files
    for lang_name, result in language_results.items():
        if result["uncovered"]:
            print("=" * 80)
            print(f"{lang_name.upper()} FILES NOT IN BAZEL TARGETS")
            print("=" * 80)
            for dir_name, files in sorted(result["uncovered"].items()):
                print(f"\n{dir_name}/ ({len(files)} files)")
                for f in sorted(files)[:10]:
                    print(f"  - {f}")
                if len(files) > 10:
                    print(f"  ... and {len(files) - 10} more")
            print()

    # Print general untracked files
    if untracked_by_dir:
        print("=" * 80)
        print("OTHER FILES IN GIT BUT NOT IN ANY BAZEL TARGET")
        print("=" * 80)
        print("(Files not tracked by language-specific scans)")
        print()
        total_untracked = sum(len(v) for v in untracked_by_dir.values())
        print(f"Total: {total_untracked} files")
        print()
        for dir_name, files in sorted(untracked_by_dir.items()):
            print(f"\n{dir_name}/ ({len(files)} files)")
            for f in sorted(files)[:5]:
                print(f"  - {f}")
            if len(files) > 5:
                print(f"  ... and {len(files) - 5} more")
        print()

    print("=" * 80)
    print("INTENTIONALLY EXCLUDED")
    print("=" * 80)
    # Combine intentional exclusions from all sources
    all_intentional: dict[str, int] = defaultdict(int)
    for result in language_results.values():
        for dir_name, files in result["intentional"].items():
            all_intentional[dir_name] += len(files)
    for dir_name, files in untracked_intentional.items():
        all_intentional[dir_name] += len(files)

    for dir_name, count in sorted(all_intentional.items()):
        print(f"  {dir_name}/ ({count} files)")
    print()


if __name__ == "__main__":
    analyze()
