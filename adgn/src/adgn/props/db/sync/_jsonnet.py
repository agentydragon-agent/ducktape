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

# Jsonnet library directory (for lib.libsonnet resolution)
# Path: db/sync/_jsonnet.py → db/sync/ → db/ → props/ → specimens/
JSONNET_LIBDIR = Path(__file__).resolve().parent.parent.parent / "specimens"


def evaluate_snapshot_issues(snapshot_dir: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Evaluate all Jsonnet issue files in a snapshot directory.

    ⚠️ SYNC PATH ONLY - use IssueData.from_db() everywhere else.

    This is the ONLY function in the codebase that evaluates jsonnet files.
    It reads all *.libsonnet files from the snapshot directory and returns
    raw dicts for true positives and false positives.

    The caller is responsible for:
    - Validating the raw dicts into Pydantic models
    - Writing them to the database
    - Never calling this function again after sync

    Args:
        snapshot_dir: Snapshot directory containing *.libsonnet files

    Returns:
        Tuple of (true_positives, false_positives) dicts.
        Each dict maps issue_id -> raw dict (with id and should_flag injected).

    Raises:
        SnapshotIssuesLoadError: If evaluation fails or structure is invalid
    """
    if not snapshot_dir.is_dir():
        raise SnapshotIssuesLoadError([f"Snapshot directory not found: {snapshot_dir}"])

    # Discover all libsonnet files in the directory
    issue_files = sorted(snapshot_dir.glob("*.libsonnet"))
    if not issue_files:
        raise SnapshotIssuesLoadError([f"No issue files found in: {snapshot_dir}"])

    # Build Jsonnet snippet to batch-load all files
    imports = []
    for p in issue_files:
        name = p.stem
        abs_path = str(p.resolve())
        imports.append(f"  {json.dumps(name)}: (import {json.dumps(abs_path)}) + {{id: {json.dumps(name)}}}")

    snippet = "{\n" + ",\n".join(imports) + "\n}"

    # Evaluate jsonnet (⚠️ THE ONLY PLACE THIS HAPPENS)
    # Uses jpathdir for lib.libsonnet resolution; nested imports work via default resolution
    eval_snippet = cast(Callable[..., Any], _jsonnet.evaluate_snippet)
    try:
        raw_obj = eval_snippet("<batch:flat>", snippet, jpathdir=[str(JSONNET_LIBDIR)])
    except Exception as e:
        raise SnapshotIssuesLoadError([f"Jsonnet evaluation failed: {e}"]) from e

    if not isinstance(raw_obj, str):
        raise SnapshotIssuesLoadError(["Jsonnet returned non-string"])

    all_issues = json.loads(raw_obj)
    if not isinstance(all_issues, dict):
        raise SnapshotIssuesLoadError([f"Expected dict, got {type(all_issues)}"])

    # Split into TPs and FPs based on occurrence structure
    true_positives: dict[str, dict] = {}
    false_positives: dict[str, dict] = {}

    for issue_id, issue_dict in all_issues.items():
        if not isinstance(issue_dict, dict):
            continue

        occurrences = issue_dict.get("occurrences", [])
        if not occurrences:
            continue

        # Check first occurrence to determine type
        first_occ = occurrences[0]
        is_tp = "expect_caught_from" in first_occ
        is_fp = "relevant_files" in first_occ

        if is_tp:
            issue_dict["should_flag"] = True
            true_positives[issue_id] = issue_dict
        elif is_fp:
            issue_dict["should_flag"] = False
            false_positives[issue_id] = issue_dict
        else:
            raise SnapshotIssuesLoadError(
                [
                    f"Issue {issue_id!r}: First occurrence is malformed - "
                    f"must have either 'expect_caught_from' (TP) or 'relevant_files' (FP), got keys: {list(first_occ.keys())}"
                ]
            )

    return true_positives, false_positives
