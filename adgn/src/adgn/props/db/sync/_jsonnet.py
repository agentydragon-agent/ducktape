"""Internal sync machinery - evaluates jsonnet to populate database.

⚠️⚠️⚠️ DO NOT IMPORT THIS MODULE OUTSIDE db/sync/ ⚠️⚠️⚠️

This module contains the ONLY code in the codebase that evaluates jsonnet files.
It exists solely to support the one-time sync operation: disk → database.

After sync completes, ALL code must load issues from the database using ORM models.

DO NOT:
- Import this module from application code, tests, or CLI commands
- Use jsonnet evaluation for runtime issue loading
- Add jsonnet evaluation anywhere else in the codebase

See docs/plans/decouple-hydration-from-issue-loading.md for architecture details.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
from pathlib import Path
from typing import Any, cast

import _jsonnet  # type: ignore[import-untyped]

from adgn.props.models.true_positive import SnapshotIssuesLoadError

logger = logging.getLogger(__name__)


def evaluate_snapshot_issues(snapshot_dir: Path, specimens_base: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Evaluate all Jsonnet issue files in a snapshot directory.

    ⚠️ SYNC PATH ONLY - use IssueData.from_db() everywhere else.

    This is the ONLY function in the codebase that evaluates jsonnet files.
    It reads all *.libsonnet files from the snapshot's issues/ subdirectory and
    returns raw dicts for true positives and false positives.

    The caller is responsible for:
    - Validating the raw dicts into Pydantic models
    - Writing them to the database
    - Never calling this function again after sync

    Args:
        snapshot_dir: Snapshot directory containing an issues/ subdirectory with *.libsonnet files
        specimens_base: Base specimens directory (for lib.libsonnet resolution via jpathdir)

    Returns:
        Tuple of (true_positives, false_positives) dicts.
        Each dict maps issue_id -> raw dict (with id and should_flag injected).

    Raises:
        SnapshotIssuesLoadError: If evaluation fails or structure is invalid
    """
    if not snapshot_dir.is_dir():
        raise SnapshotIssuesLoadError([f"Snapshot directory not found: {snapshot_dir}"])

    # Discover all libsonnet files in the issues subdirectory
    issues_subdir = snapshot_dir / "issues"
    if not issues_subdir.is_dir():
        raise SnapshotIssuesLoadError([f"Issues subdirectory not found: {issues_subdir}"])

    issue_files = sorted(issues_subdir.glob("*.libsonnet"))
    if not issue_files:
        raise SnapshotIssuesLoadError([f"No issue files found in: {issues_subdir}"])

    # Build Jsonnet snippet to batch-load all files and separate TPs/FPs
    imports = []
    for p in issue_files:
        name = p.stem
        abs_path = str(p.resolve())
        imports.append(f"  {json.dumps(name)}: (import {json.dumps(abs_path)}) + {{id: {json.dumps(name)}}}")

    # Generate snippet that separates TPs and FPs in Jsonnet
    snippet = (
        "local all = {\n" + ",\n".join(imports) + "\n};\n"
        "{\n"
        "  tps: {[k]: all[k] for k in std.objectFields(all) if all[k].should_flag == true},\n"
        "  fps: {[k]: all[k] for k in std.objectFields(all) if all[k].should_flag == false},\n"
        "}"
    )

    # Evaluate jsonnet (⚠️ THE ONLY PLACE THIS HAPPENS)
    # Uses jpathdir for lib.libsonnet resolution; nested imports work via default resolution
    eval_snippet = cast(Callable[..., Any], _jsonnet.evaluate_snippet)
    try:
        raw_obj = eval_snippet("<batch:separated>", snippet, jpathdir=[str(specimens_base)])
    except Exception as e:
        raise SnapshotIssuesLoadError([f"Jsonnet evaluation failed: {e}"]) from e

    if not isinstance(raw_obj, str):
        raise SnapshotIssuesLoadError(["Jsonnet returned non-string"])

    result = json.loads(raw_obj)
    if not isinstance(result, dict):
        raise SnapshotIssuesLoadError([f"Expected dict, got {type(result)}"])

    # Extract pre-separated TPs and FPs from Jsonnet
    true_positives = result.get("tps", {})
    false_positives = result.get("fps", {})

    if not isinstance(true_positives, dict):
        raise SnapshotIssuesLoadError([f"Expected tps to be dict, got {type(true_positives)}"])
    if not isinstance(false_positives, dict):
        raise SnapshotIssuesLoadError([f"Expected fps to be dict, got {type(false_positives)}"])

    return true_positives, false_positives
