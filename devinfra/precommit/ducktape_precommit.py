"""Unified pre-commit entry point for the ducktape wheel.

Runs all custom validations and optionally enforces Bazel test cache.
Installed as `ducktape-precommit` console script via the claude-hooks wheel.

Validations (always run):
- pytest-main-check: test files have pytest_bazel.main() entry points
- tf-centralization: terraform modules don't define provider versions
- filename-conventions: new .py/.md files use underscores not dashes
- cluster-validate: kustomize/helm/dependency validation
- frozen-specimens: block changes to code/ in committed specimen snapshots

Optional (guarded by DUCKTAPE_PRECOMMIT_ENFORCE_BAZEL_TESTS=1):
- enforce-bazel-tests: affected Bazel tests are cached and passing
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pygit2
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import StatusCode

from cluster.validation.validate_all import validate as validate_cluster
from devinfra.precommit.enforce_bazel_tests.enforce_bazel_tests import (
    EnforceBazelTestsError,
    run as enforce_bazel_tests_run,
)
from devinfra.precommit.filename_conventions import check_filename_conventions
from devinfra.precommit.frozen_specimens import check_specimen_code_changes
from devinfra.precommit.terraform_centralization import find_violations
from devinfra.pytest_main import BazelPyTestIndex, build_bazel_index, check_files_async
from util.bazel.workspace import BazelWorkspace, detect_bazel_command
from util.otel import JsonlSpanExporter

_IGNORE_ATTRS = ("linguist-generated", "gitlab-generated", "rules-lint-ignored", "filename-conventions-ignored")

tracer = trace.get_tracer(__name__)


def _is_ignored(repo: pygit2.Repository, path: str) -> bool:
    return any(repo.get_attr(path, a) in (True, "true") for a in _IGNORE_ATTRS)


def is_cluster_validated(p: Path) -> bool:
    if p.is_relative_to("cluster/k8s") and p.suffix in (".yaml", ".yml"):
        return True
    return p.is_relative_to("cluster/terraform") and "cilium" in p.parts


def is_terraform_module(p: Path) -> bool:
    return p.suffix == ".tf" and p.is_relative_to("cluster/terraform/modules")


async def run_pytest_main_check(
    files: list[Path], repo_root: Path, bazel_index: BazelPyTestIndex
) -> tuple[str, str | None]:
    """Check that test files have pytest_bazel.main() calls.

    Returns (name, error_output | None).
    """
    if not files:
        candidates = [p.relative_to(repo_root) for p in bazel_index.known_srcs]
    else:
        candidates = [f for f in files if (repo_root / f).resolve() in bazel_index.known_srcs]

    test_files = [f for f in candidates if f.name != "conftest.py"]

    if not test_files:
        return ("pytest-main-check", None)

    results = await check_files_async(test_files, repo_root, bazel_index)
    failed = [r for r in results if not r.passed]
    if failed:
        return ("pytest-main-check", "\n".join(f"{r.file_path}: {r.reason}" for r in failed))
    return ("pytest-main-check", None)


async def run_cluster_validate(files: list[Path], repo_root: Path) -> tuple[str, str | None]:
    if not any(is_cluster_validated(f) for f in files):
        return ("cluster-validate", None)
    errors = await validate_cluster(repo_root / "cluster/k8s", skip_flux_build=True)
    if errors:
        return ("cluster-validate", "\n".join(f"  {e.strip()}" for e in errors))
    return ("cluster-validate", None)


async def run_terraform_centralization_check(files: list[Path], repo_root: Path) -> tuple[str, str | None]:
    if not any(is_terraform_module(f) for f in files):
        return ("tf-centralization", None)
    violations = find_violations(repo_root)
    if violations:
        return ("tf-centralization", "\n".join(str(v) for v in violations))
    return ("tf-centralization", None)


async def run_filename_convention_check(
    deltas: list[pygit2.DiffDelta], head_tree: pygit2.Tree | None
) -> tuple[str, str | None]:
    violations = check_filename_conventions(deltas, head_tree)
    if violations:
        return ("filename-conventions", "\n".join(violations))
    return ("filename-conventions", None)


async def run_frozen_specimens_check(
    deltas: list[pygit2.DiffDelta], head_tree: pygit2.Tree | None
) -> tuple[str, str | None]:
    violations = check_specimen_code_changes(deltas, head_tree)
    if violations:
        msg = "Changes to code/ in committed snapshots are not allowed.\n"
        msg += "\n".join(f"  {v}" for v in violations)
        return ("frozen-specimens", msg)
    return ("frozen-specimens", None)


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


def _setup_tracing(repo_root: Path) -> None:
    provider = TracerProvider()
    exporter = JsonlSpanExporter(repo_root / ".git" / "precommit-traces.jsonl")
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


async def main_async() -> int:
    repo_root = get_repo_root()
    repo = pygit2.Repository(str(repo_root))
    _setup_tracing(repo_root)

    with tracer.start_as_current_span("precommit"):
        workspace = BazelWorkspace(root=repo_root, bazel_command=detect_bazel_command())
        bazel_index = build_bazel_index(workspace)

        # Compute staged deltas once (fast index-to-HEAD diff)
        if repo.head_is_unborn:
            head_tree = None
            base = repo[repo.TreeBuilder().write()].peel(pygit2.Tree)
        else:
            head_tree = repo.head.peel(pygit2.Tree)
            base = head_tree
        repo.index.read()
        all_deltas = list(repo.index.diff_to_tree(base).deltas)

        # Filter out ignored paths before dispatching to checks
        deltas = [d for d in all_deltas if not _is_ignored(repo, d.new_file.path)]

        files = [Path(f) for f in sys.argv[1:]] if len(sys.argv) > 1 else get_all_files(repo)

        # Run validations concurrently, each wrapped in a span
        async def _traced(coro) -> tuple[str, str | None]:
            name, error = await coro
            span = trace.get_current_span()
            span.set_attribute("validation.name", name)
            if error:
                span.set_status(StatusCode.ERROR, error[:200])
            return (name, error)

        print(f"Validating {len(files)} files...")
        results = list(
            await asyncio.gather(
                _traced(run_pytest_main_check(files, repo_root, bazel_index)),
                _traced(run_terraform_centralization_check(files, repo_root)),
                _traced(run_filename_convention_check(deltas, head_tree)),
                _traced(run_cluster_validate(files, repo_root)),
                _traced(run_frozen_specimens_check(deltas, head_tree)),
            )
        )

        failed = []
        for name, error in results:
            if error:
                print(f"  {name}: FAILED")
                print(error, file=sys.stderr)
                failed.append(name)
            else:
                print(f"  {name}: ok")

        # Enforce Bazel tests only when explicitly enabled
        if os.environ.get("DUCKTAPE_PRECOMMIT_ENFORCE_BAZEL_TESTS") in ("1", "true"):
            try:
                enforce_bazel_tests_run(workspace, deltas)
            except EnforceBazelTestsError as e:
                print(f"enforce-bazel-tests: {e}", file=sys.stderr)
                return 1

    return 1 if failed else 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
