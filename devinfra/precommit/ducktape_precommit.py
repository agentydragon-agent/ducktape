"""Unified pre-commit entry point for the ducktape wheel.

Runs all custom validations and optionally enforces Bazel test cache.
Installed as `ducktape-precommit` console script via the claude-hooks wheel.

Validations (always run):
- pytest-main-check: test files have pytest_bazel.main() entry points
- tf-centralization: terraform modules don't define provider versions
- filename-conventions: new .py/.md files use underscores not dashes
- cluster-validate: kustomize/helm/dependency validation

Optional (guarded by DUCKTAPE_PRECOMMIT_ENFORCE_BAZEL_TESTS=1):
- enforce-bazel-tests: affected Bazel tests are cached and passing
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pygit2

from cluster.scripts.validate_cluster.main import validate as validate_cluster
from devinfra.precommit.enforce_bazel_tests.enforce_bazel_tests import (
    EnforceBazelTestsError,
    run as enforce_bazel_tests_run,
)
from devinfra.precommit.filename_conventions import check_filename_conventions
from devinfra.precommit.terraform_centralization import find_violations
from devinfra.pytest_main import BazelPyTestIndex, build_bazel_index, check_files_async
from util.bazel.workspace import BazelWorkspace, detect_bazel_command

_LINT_IGNORED_ATTRS = ("linguist-generated", "gitlab-generated", "rules-lint-ignored")


def is_lint_ignored(repo: pygit2.Repository, path: Path) -> bool:
    return any(repo.get_attr(str(path), attr) in (True, "true") for attr in _LINT_IGNORED_ATTRS)


@dataclass
class Skipped:
    pass


@dataclass
class Failed:
    elapsed: float
    output: str


@dataclass
class Passed:
    elapsed: float


ValidationOutcome = Skipped | Failed | Passed


@dataclass
class ValidationResult:
    name: str
    outcome: ValidationOutcome


def is_cluster_validated(p: Path) -> bool:
    if p.is_relative_to("cluster/k8s") and p.suffix in (".yaml", ".yml"):
        return True
    return p.is_relative_to("cluster/terraform") and "cilium" in p.parts


def is_terraform_module(p: Path) -> bool:
    return p.suffix == ".tf" and p.is_relative_to("cluster/terraform/modules")


async def run_pytest_main_check(
    files: list[Path], repo_root: Path, repo: pygit2.Repository, bazel_index: BazelPyTestIndex
) -> ValidationResult:
    """Check that test files have pytest_bazel.main() calls."""
    name = "pytest-main-check"
    start = time.perf_counter()

    if not files:
        candidates = [p.relative_to(repo_root) for p in bazel_index.known_srcs]
    else:
        candidates = [f for f in files if (repo_root / f).resolve() in bazel_index.known_srcs]

    test_files = [f for f in candidates if f.name != "conftest.py" and not is_lint_ignored(repo, f)]

    if not test_files:
        return ValidationResult(name, Skipped())

    results = await check_files_async(test_files, repo_root, bazel_index)
    elapsed = time.perf_counter() - start

    failed = [r for r in results if not r.passed]
    if failed:
        return ValidationResult(name, Failed(elapsed, "\n".join(f"{r.file_path}: {r.reason}" for r in failed)))
    return ValidationResult(name, Passed(elapsed))


async def run_cluster_validate(files: list[Path], repo_root: Path) -> ValidationResult:
    """Run cluster kustomization/helm/dependency validation."""
    name = "cluster-validate"
    if not any(is_cluster_validated(f) for f in files):
        return ValidationResult(name, Skipped())

    start = time.perf_counter()
    kust_errors, global_errors = await validate_cluster(repo_root / "cluster/k8s", skip_flux_build=True)
    elapsed = time.perf_counter() - start

    if kust_errors or global_errors:
        lines = [f"  {k.parent}: {err.strip()}" for k, err in kust_errors]
        lines.extend(f"  {err.strip()}" for err in global_errors)
        return ValidationResult(name, Failed(elapsed, "\n".join(lines)))
    return ValidationResult(name, Passed(elapsed))


async def run_terraform_centralization_check(files: list[Path], repo_root: Path) -> ValidationResult:
    """Check terraform modules don't define provider versions."""
    name = "tf-centralization"
    if not any(is_terraform_module(f) for f in files):
        return ValidationResult(name, Skipped())

    start = time.perf_counter()
    violations = find_violations(repo_root)
    elapsed = time.perf_counter() - start

    if violations:
        return ValidationResult(name, Failed(elapsed, "\n".join(str(v) for v in violations)))
    return ValidationResult(name, Passed(elapsed))


async def run_filename_convention_check(repo: pygit2.Repository) -> ValidationResult:
    """Check that new .py/.md files and directories use underscores, not dashes."""
    name = "filename-conventions"
    start = time.perf_counter()
    violations = check_filename_conventions(repo)
    elapsed = time.perf_counter() - start
    if violations:
        return ValidationResult(name, Failed(elapsed, "\n".join(violations)))
    return ValidationResult(name, Passed(elapsed))


def get_repo_root() -> Path:
    """Find repo root by walking up from cwd looking for .git."""
    path = Path.cwd()
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("Not inside a git repository")


def get_all_files(repo: pygit2.Repository) -> list[Path]:
    """Get all tracked files from git index, excluding deleted files."""
    repo_root = Path(repo.workdir)
    return [Path(entry.path) for entry in repo.index if (repo_root / entry.path).exists()]


async def main_async() -> int:
    profile = os.environ.get("PRECOMMIT_PROFILE", "").lower() in ("1", "true", "yes")

    t0 = time.perf_counter()

    repo_root = get_repo_root()
    repo = pygit2.Repository(str(repo_root))
    workspace = BazelWorkspace(root=repo_root, bazel_command=detect_bazel_command())
    t1 = time.perf_counter()

    bazel_index = build_bazel_index(workspace)

    files = [Path(f) for f in sys.argv[1:]] if len(sys.argv) > 1 else get_all_files(repo)
    t2 = time.perf_counter()

    if profile:
        print(f"[profile] setup: {t1 - t0:.2f}s, get_files: {t2 - t1:.2f}s")

    # Run validations
    print(f"Validating {len(files)} files...")
    start_total = time.perf_counter()
    results = list(
        await asyncio.gather(
            run_pytest_main_check(files, repo_root, repo, bazel_index),
            run_terraform_centralization_check(files, repo_root),
            run_filename_convention_check(repo),
            run_cluster_validate(files, repo_root),
        )
    )

    failed = []
    for vresult in results:
        match vresult.outcome:
            case Skipped():
                pass
            case Passed(elapsed=elapsed):
                print(f"  {vresult.name}: {elapsed:.1f}s")
            case Failed(elapsed=elapsed, output=output):
                print(f"  {vresult.name}: FAILED ({elapsed:.1f}s)")
                failed.append(vresult)
                if output:
                    print(output, file=sys.stderr)

    elapsed_total = time.perf_counter() - start_total
    print(f"\nTotal: {elapsed_total:.1f}s")

    # Enforce Bazel tests only when explicitly enabled
    if os.environ.get("DUCKTAPE_PRECOMMIT_ENFORCE_BAZEL_TESTS") in ("1", "true"):
        try:
            enforce_bazel_tests_run(workspace, repo)
        except EnforceBazelTestsError as e:
            print(f"enforce-bazel-tests: {e}", file=sys.stderr)
            return 1

    return 1 if failed else 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
