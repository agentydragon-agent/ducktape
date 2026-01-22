#!/usr/bin/env python3
"""Compute affected Bazel targets using bazel-diff.

Outputs to $GITHUB_OUTPUT:
    targets: space-separated list of affected targets, or "//..." for full build
    has_changes: "true" or "false"
    has_props: "true" if //props/... targets are affected
    has_editor_agent: "true" if //editor_agent/... targets are affected
    has_agent_server: "true" if //agent_server/... targets are affected
    has_finance: "true" if //finance/... targets are affected
    has_props_frontend: "true" if //props/frontend/... targets are affected
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BAZEL_DIFF_VERSION = "12.1.1"
BAZEL_DIFF_URL = f"https://github.com/Tinder/bazel-diff/releases/download/{BAZEL_DIFF_VERSION}/bazel-diff_deploy.jar"

# Infrastructure patterns that require full build (changes affect all targets)
INFRA_PATTERNS = [
    r"^MODULE\.bazel$",
    r"^MODULE\.bazel\.lock$",
    r"^requirements_bazel\.txt$",
    r"^\.bazelrc$",
    r"^\.bazelversion$",
    r"^tools/",
    r"^WORKSPACE",
]

# Path patterns for conditional job triggers
PATH_PATTERNS = {
    "has_props": "//props/...",
    "has_editor_agent": "//editor_agent/...",
    "has_agent_server": "//agent_server/...",
    "has_finance": "//finance/...",
    "has_props_frontend": "//props/frontend/...",
}


@dataclass
class AffectedTargets:
    """Result of computing affected targets."""

    targets: str  # Space-separated targets or "//..."
    has_changes: bool


def run_cmd(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command, optionally checking return code."""
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def download_bazel_diff(dest: Path) -> None:
    """Download bazel-diff JAR.

    Raises:
        Exception: If download fails (not swallowed - this is a hard failure)
    """
    print(f"Downloading bazel-diff v{BAZEL_DIFF_VERSION}...")
    urllib.request.urlretrieve(BAZEL_DIFF_URL, dest)
    print(f"Downloaded to {dest}")


def get_changed_files(base_sha: str) -> list[str]:
    """Get list of files changed between base_sha and HEAD."""
    result = run_cmd(["git", "diff", "--name-only", f"{base_sha}...HEAD"], capture=True)
    return [f for f in result.stdout.strip().split("\n") if f]


def has_infra_changes(changed_files: list[str]) -> bool:
    """Check if any changed files match infrastructure patterns."""
    for pattern in INFRA_PATTERNS:
        regex = re.compile(pattern)
        for f in changed_files:
            if regex.match(f):
                return True
    return False


def get_base_sha() -> str | None:
    """Determine base SHA for comparison."""
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")

    if event_name == "pull_request":
        base_ref = os.environ.get("GITHUB_BASE_REF", "")
        result = run_cmd(["git", "merge-base", f"origin/{base_ref}", "HEAD"], capture=True)
        sha = result.stdout.strip()
        print(f"Pull request: comparing against merge-base {sha}")
        return sha
    result = run_cmd(["git", "rev-parse", "HEAD~1"], check=False, capture=True)
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    print(f"Push: comparing against HEAD~1 ({sha})")
    return sha


def run_bazel_diff(jar_path: Path, workspace: str, base_sha: str) -> list[str] | None:
    """Run bazel-diff to compute impacted targets.

    Returns:
        List of impacted targets, or None on failure (triggers full build fallback)
    """
    current_sha = run_cmd(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()

    with tempfile.TemporaryDirectory() as tmpdir:
        base_json = Path(tmpdir) / "base.json"
        head_json = Path(tmpdir) / "head.json"
        targets_file = Path(tmpdir) / "targets.txt"

        # Generate hashes for base commit
        print(f"Generating hashes for base commit {base_sha}...")
        run_cmd(["git", "checkout", "--quiet", base_sha])

        result = run_cmd(
            ["java", "-jar", jar_path, "generate-hashes", "-w", workspace, "-b", "bazelisk", base_json], check=False
        )
        if result.returncode != 0:
            print("Base hash generation failed, falling back to full build")
            run_cmd(["git", "checkout", "--quiet", current_sha])
            return None

        # Generate hashes for head commit
        print(f"Generating hashes for head commit {current_sha}...")
        run_cmd(["git", "checkout", "--quiet", current_sha])

        result = run_cmd(
            ["java", "-jar", jar_path, "generate-hashes", "-w", workspace, "-b", "bazelisk", head_json], check=False
        )
        if result.returncode != 0:
            print("Head hash generation failed, falling back to full build")
            return None

        # Compute impacted targets
        print("Computing impacted targets...")
        result = run_cmd(
            ["java", "-jar", jar_path, "get-impacted-targets", "-sh", base_json, "-fh", head_json, "-o", targets_file],
            check=False,
        )
        if result.returncode != 0:
            print("Target diff failed, falling back to full build")
            return None

        if not targets_file.exists() or targets_file.stat().st_size == 0:
            return []

        return [t for t in targets_file.read_text().strip().split("\n") if t]


def compute_affected_targets() -> AffectedTargets:
    """Compute affected Bazel targets.

    Returns:
        AffectedTargets with targets string and has_changes flag
    """
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    workspace = os.environ.get("GITHUB_WORKSPACE") or str(Path.cwd())

    # Full build on main/devel branches (only use diffs for PRs)
    if event_name != "pull_request":
        print(f"Push to {ref_name} branch, running full build")
        return AffectedTargets(targets="//...", has_changes=True)

    # Download bazel-diff (failure is fatal, not swallowed)
    jar_path = Path("/tmp/bazel-diff.jar")
    download_bazel_diff(jar_path)

    # Get base SHA
    base_sha = get_base_sha()
    if not base_sha:
        print("No base SHA (new branch or initial commit), running all targets")
        return AffectedTargets(targets="//...", has_changes=True)

    # Check changed files
    changed_files = get_changed_files(base_sha)
    print("Changed files:")
    for f in changed_files[:20]:
        print(f"  {f}")
    if len(changed_files) > 20:
        print(f"  ... and {len(changed_files) - 20} more")

    # Check for infrastructure changes
    if has_infra_changes(changed_files):
        print("Infrastructure change detected, running all targets")
        return AffectedTargets(targets="//...", has_changes=True)

    # Run bazel-diff
    targets = run_bazel_diff(jar_path, workspace, base_sha)

    if targets is None:
        # Fallback to full build on bazel-diff failure
        return AffectedTargets(targets="//...", has_changes=True)

    if not targets:
        print("No Bazel targets affected")
        return AffectedTargets(targets="", has_changes=False)

    print(f"Found {len(targets)} affected targets")
    if len(targets) <= 20:
        for t in targets:
            print(f"  {t}")
    else:
        for t in targets[:20]:
            print(f"  {t}")
        print(f"  ... and {len(targets) - 20} more")

    return AffectedTargets(targets=" ".join(targets), has_changes=True)


def check_intersection(targets: str, pattern: str) -> bool:
    """Check if affected targets intersect with a pattern using bazel query.

    Args:
        targets: Space-separated target list or "//..."
        pattern: Bazel pattern like "//props/..."

    Returns:
        True if intersection is non-empty
    """
    if not targets:
        return False

    # Full build checks pattern directly; otherwise compute set intersection
    query = pattern if targets == "//..." else f"set({targets}) intersect {pattern}"

    result = run_cmd(["bazelisk", "query", query], check=False, capture=True)
    # Non-empty output means intersection exists
    return bool(result.stdout.strip())


def compute_intersections(targets: str, has_changes: bool) -> dict[str, bool]:
    """Compute intersection flags for all path patterns."""
    if not has_changes:
        return dict.fromkeys(PATH_PATTERNS, False)

    print("Computing path intersections...")
    return {var_name: check_intersection(targets, pattern) for var_name, pattern in PATH_PATTERNS.items()}


def output_results(affected: AffectedTargets, intersections: dict[str, bool]) -> None:
    """Write results to $GITHUB_OUTPUT."""
    output_file = os.environ.get("GITHUB_OUTPUT")

    lines = [f"targets={affected.targets}", f"has_changes={'true' if affected.has_changes else 'false'}"]
    for var_name, has_intersection in intersections.items():
        lines.append(f"{var_name}={'true' if has_intersection else 'false'}")

    if not output_file:
        # Print to stdout if not in GitHub Actions
        for line in lines:
            print(line)
        return

    with Path(output_file).open("a") as f:
        for line in lines:
            f.write(f"{line}\n")


def main() -> None:
    # Step 1: Compute affected targets
    affected = compute_affected_targets()

    # Step 2: Compute intersections with path patterns
    intersections = compute_intersections(affected.targets, affected.has_changes)

    # Step 3: Output results
    output_results(affected, intersections)


if __name__ == "__main__":
    main()
