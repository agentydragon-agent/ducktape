#!/usr/bin/env python3
"""Pre-commit hook: verify affected Bazel tests are cached and passing.

Uses pygit2 for fast staged file discovery, then:
1. Converts staged files to Bazel source file labels
2. Finds affected test targets via rdeps query
3. Checks tests are up-to-date via --check_tests_up_to_date

Requires --remote_download_minimal (or --remote_download_toplevel) in .bazelrc
for --check_tests_up_to_date to work with RBE. Without this, test results only
exist in the remote cache and the check always reports "not up-to-date".
See https://github.com/bazelbuild/bazel/issues/3978 for details.

Currently set as `build:rbe --remote_download_minimal` in .bazelrc.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pygit2

# Infrastructure files that affect too many targets — CI catches these.
_INFRA_PATTERNS = (
    "MODULE.bazel",
    "MODULE.bazel.lock",
    "requirements_bazel.txt",
    ".bazelrc",
    ".bazelversion",
    "WORKSPACE",
    "WORKSPACE.bazel",
    "WORKSPACE.bzlmod",
)
_INFRA_GLOBS = ("devinfra/bazel*",)

_PREFIX = "enforce-bazel-tests"


def _is_infra_file(path: str) -> bool:
    if path in _INFRA_PATTERNS:
        return True
    return any(fnmatch.fnmatch(path, g) for g in _INFRA_GLOBS)


def _get_staged_files(repo: pygit2.Repository) -> list[str]:
    """Get staged file paths using fast index-to-HEAD diff.

    Uses index.diff_to_tree(HEAD) instead of repo.status() — the latter
    triggers ~160k syscalls on 9p filesystems (~12s). diff_to_tree only
    compares the index to HEAD (~0.003s).
    """
    try:
        head_tree = repo.head.peel(pygit2.Tree)
    except pygit2.GitError:
        head_tree = None

    repo.index.read()
    if head_tree is not None:
        diff = repo.index.diff_to_tree(head_tree)
        return [delta.new_file.path for delta in diff.deltas]
    return [entry.path for entry in repo.index]


def _find_bazel_package(filepath: Path, repo_root: Path) -> Path | None:
    """Find the Bazel package containing a file by walking up to find BUILD."""
    current = repo_root / filepath.parent
    while current >= repo_root:
        if (current / "BUILD.bazel").exists() or (current / "BUILD").exists():
            return current.relative_to(repo_root)
        if current == repo_root:
            break
        current = current.parent
    return None


def _file_to_label(filepath: str, repo_root: Path) -> str | None:
    """Convert a repo-relative filepath to a Bazel source file label."""
    path = Path(filepath)
    pkg = _find_bazel_package(path, repo_root)
    if pkg is None:
        return None
    pkg_str = "" if pkg == Path() else str(pkg)
    rel = path.relative_to(pkg) if pkg != Path() else path
    return f"//{pkg_str}:{rel}"


def _run_bazel_query(expr: str, *, cwd: Path, timeout: int | None = None) -> list[str]:
    """Run bazel query and return target labels.

    Uses --query_file to avoid E2BIG on large queries. Pattern from
    util/bazel/query.py (inlined here so the script is self-contained
    for pre-commit's virtualenv).

    TODO: Uninline this once util.bazel.query is pip-installable or the hook
    runs via Bazel (language: system).
    """
    cmd = ["bazel", "query", "--output=label"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bazelquery", delete=False) as f:
        f.write(expr)
        f.flush()
        cmd.append(f"--query_file={f.name}")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False, timeout=timeout)
    os.unlink(f.name)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, "bazel query", result.stdout, result.stderr)
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    repo = pygit2.Repository(".")
    repo_root = Path(repo.workdir).resolve()

    staged = _get_staged_files(repo)
    if not staged:
        return 0

    if any(_is_infra_file(f) for f in staged):
        print(f"{_PREFIX}: infrastructure file changed, skipping (CI catches these)")
        return 0

    labels: list[str] = []
    for f in staged:
        label = _file_to_label(f, repo_root)
        if label is not None:
            labels.append(label)

    if not labels:
        return 0

    # Use `intersect` to filter out labels that aren't valid Bazel targets.
    # Not all files in a Bazel package are source targets — e.g.
    # .pre-commit-config.yaml in the root package isn't in any BUILD srcs.
    labels_set = " ".join(labels)
    query_expr = f'kind(".*_test", rdeps(//..., set({labels_set}) ^ //...:*))'

    timeout = int(os.environ.get("DUCKTAPE_BAZEL_QUERY_TIMEOUT", "120"))

    try:
        targets = _run_bazel_query(query_expr, cwd=repo_root, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"{_PREFIX}: bazel query timed out after {timeout}s", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"{_PREFIX}: bazel query failed (exit {e.returncode})", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"{_PREFIX}: bazel not found on PATH", file=sys.stderr)
        return 1

    if not targets:
        return 0

    print(f"{_PREFIX}: checking {len(targets)} affected test(s)...")

    cmd = ["bazel", "test", "--check_tests_up_to_date", "--config=nolint", *targets]
    try:
        result = subprocess.run(cmd, check=False, cwd=repo_root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"{_PREFIX}: bazel test timed out after {timeout}s", file=sys.stderr)
        return 1

    if result.returncode == 0:
        return 0

    print(f"{_PREFIX}: affected tests are not up-to-date or failing.", file=sys.stderr)
    print(f"Run: bazel test {' '.join(targets)}", file=sys.stderr)
    if result.stderr:
        lines = result.stderr.strip().splitlines()
        for line in lines[-20:]:
            print(f"  {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
