#!/usr/bin/env python3
"""Audit Bazelization coverage in the repository.

Compares git-tracked source files against files in Bazel targets.

Usage:
    bazel run //bazelization:audit
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
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


@dataclass
class CategorizedFiles:
    """Files categorized by coverage status."""

    covered: list[Path]
    uncovered: dict[str, list[Path]]
    intentional: dict[str, list[Path]]


@dataclass
class LanguageResult:
    """Results of analyzing a single language."""

    config: LanguageConfig
    git_files: set[Path]
    bazel_files: set[Path]
    categorized: CategorizedFiles


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


def label_to_path(label: str) -> Path | None:
    """Convert Bazel label to file path.

    Examples:
        //pkg:path/to/file.py -> pkg/path/to/file.py
        //:file.py -> file.py
        //pkg:BUILD.bazel -> pkg/BUILD.bazel

    Returns None for non-file labels (targets without colons or starting with @).
    """
    if label.startswith("@") or ":" not in label:
        return None

    label = label.removeprefix("//")
    pkg, file = label.split(":", 1)

    # Skip if it looks like a target name (starts with underscore or no file extension)
    if file.startswith("_") and "." not in file:
        return None

    return Path(pkg) / file if pkg else Path(file)


def batch_bazel_query(query_expr: str) -> set[str]:
    """Execute a Bazel query and return results as a set of labels."""
    result = subprocess.run(
        ["bazel", "query", query_expr],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        return set()

    return {line for line in result.stdout.strip().split("\n") if line}


def find_git_files(extensions: list[str] | None = None) -> set[Path]:
    """Find git-tracked files, optionally filtered by extensions."""
    repo = pygit2.Repository(REPO_ROOT)
    index = repo.index
    index.read()

    if extensions is None:
        return {Path(entry.path) for entry in index}

    return {
        Path(entry.path)
        for entry in index
        if any(entry.path.endswith(ext) for ext in extensions)
    }


def find_bazel_files_by_language(lang_config: LanguageConfig) -> set[Path]:
    """Query Bazel for files of a specific language in specified target kinds and attributes.

    Batches queries by kind to minimize Bazel invocations.
    """
    # Build batched query: union of all (kind, attr) combinations
    queries = [
        f'labels({attr}, kind("{kind}", //...))'
        for kind in lang_config.bazel_kinds
        for attr in lang_config.bazel_attrs
    ]

    # Batch all queries into one union expression
    query_expr = " + ".join(queries) if queries else '""'
    labels = batch_bazel_query(query_expr)

    # Convert labels to paths and filter by extension
    paths = {label_to_path(label) for label in labels}
    return {
        p for p in paths
        if p is not None and any(str(p).endswith(ext) for ext in lang_config.extensions)
    }


def find_all_bazel_inputs() -> set[Path]:
    """Find all files that are inputs to any Bazel target (srcs + data)."""
    query_expr = "labels(srcs, //...) + labels(data, //...)"
    labels = batch_bazel_query(query_expr)

    paths = {label_to_path(label) for label in labels}
    return {p for p in paths if p is not None}


def categorize_files(
    git_files: set[Path],
    bazel_files: set[Path],
    is_intentionally_excluded: Callable[[Path], bool]
) -> CategorizedFiles:
    """Categorize files into covered, uncovered, and intentionally excluded by top-level directory."""
    covered = []
    uncovered: dict[str, list[Path]] = defaultdict(list)
    intentional: dict[str, list[Path]] = defaultdict(list)

    for path in sorted(git_files):
        top_dir = path.parts[0] if path.parts else ""

        if is_intentionally_excluded(path):
            intentional[top_dir].append(path)
        elif path in bazel_files:
            covered.append(path)
        else:
            uncovered[top_dir].append(path)

    return CategorizedFiles(
        covered=covered,
        uncovered=uncovered,
        intentional=intentional,
    )


def analyze() -> None:
    print("=" * 80)
    print("BAZELIZATION COVERAGE AUDIT")
    print("=" * 80)
    print()

    # Track per-language coverage
    language_results: dict[str, LanguageResult] = {}

    for lang_config in LANGUAGES:
        print(f"Scanning {lang_config.name} files...")
        git_files = find_git_files(lang_config.extensions)
        bazel_files = find_bazel_files_by_language(lang_config)

        categorized = categorize_files(
            git_files,
            bazel_files,
            lambda p: p.parts[0] in INTENTIONALLY_EXCLUDED if p.parts else False
        )

        language_results[lang_config.name] = LanguageResult(
            config=lang_config,
            git_files=git_files,
            bazel_files=bazel_files,
            categorized=categorized,
        )

    # Find files in git but not in any Bazel target at all
    print("Scanning all Bazel inputs...")
    all_git_files = find_git_files()
    all_bazel_inputs = find_all_bazel_inputs()

    # Files tracked by language-specific scans
    all_language_tracked = set().union(*(r.git_files for r in language_results.values()))

    # Files in git but not in any Bazel target and not tracked by language scans
    git_not_in_bazel = all_git_files - all_bazel_inputs
    git_not_tracked = git_not_in_bazel - all_language_tracked

    # Categorize untracked files
    untracked_categorized = categorize_files(
        git_not_tracked,
        set(),
        lambda p: p.parts[0] in INTENTIONALLY_EXCLUDED if p.parts else False
    )

    # Query Bazel for target counts
    print("Querying Bazel targets...")
    target_counts = {
        kind: len(batch_bazel_query(f'kind("{kind}", //...)'))
        for kind in ["py_library", "py_test", "ruff_test"]
    }
    manual_targets = batch_bazel_query('attr(tags, "manual", //...)')

    # Print results
    print()
    print("=" * 80)
    print("LANGUAGE-SPECIFIC COVERAGE")
    print("=" * 80)
    print()

    for lang_name, result in language_results.items():
        total_git = len(result.git_files)
        if total_git == 0:
            continue

        total_intentional = sum(len(v) for v in result.categorized.intentional.values())
        total_uncovered = sum(len(v) for v in result.categorized.uncovered.values())
        total_covered = len(result.categorized.covered)

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
    for kind, count in target_counts.items():
        print(f"{kind:15} {count}")
    print()

    if manual_targets:
        filtered_manual = {t for t in manual_targets if not t.startswith("//:requirements")}
        if filtered_manual:
            print("Manual targets (excluded from bazel test //...):")
            for target in sorted(filtered_manual):
                print(f"  {target}")
            print()

    # Print per-language uncovered files
    for lang_name, result in language_results.items():
        if result.categorized.uncovered:
            print("=" * 80)
            print(f"{lang_name.upper()} FILES NOT IN BAZEL TARGETS")
            print("=" * 80)
            for dir_name, files in sorted(result.categorized.uncovered.items()):
                print(f"\n{dir_name}/ ({len(files)} files)")
                for f in sorted(files)[:10]:
                    print(f"  - {f}")
                if len(files) > 10:
                    print(f"  ... and {len(files) - 10} more")
            print()

    # Print general untracked files
    if untracked_categorized.uncovered:
        print("=" * 80)
        print("OTHER FILES IN GIT BUT NOT IN ANY BAZEL TARGET")
        print("=" * 80)
        print("(Files not tracked by language-specific scans)")
        print()
        total_untracked = sum(len(v) for v in untracked_categorized.uncovered.values())
        print(f"Total: {total_untracked} files")
        print()
        for dir_name, files in sorted(untracked_categorized.uncovered.items()):
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
        for dir_name, files in result.categorized.intentional.items():
            all_intentional[dir_name] += len(files)
    for dir_name, files in untracked_categorized.intentional.items():
        all_intentional[dir_name] += len(files)

    for dir_name, count in sorted(all_intentional.items()):
        print(f"  {dir_name}/ ({count} files)")
    print()


if __name__ == "__main__":
    analyze()
