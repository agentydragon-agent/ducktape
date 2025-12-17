"""Internal sync machinery - loads YAML issue files to populate database.

⚠️⚠️⚠️ DO NOT IMPORT THIS MODULE OUTSIDE db/sync/ ⚠️⚠️⚠️

This module contains YAML issue loading for the sync operation: disk → database.

After sync completes, ALL code must load issues from the database using ORM models.

DO NOT:
- Import this module from application code, tests, or CLI commands
- Use YAML loading for runtime issue loading
- Add YAML loading anywhere else in the codebase
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from adgn.props.ids import SnapshotSlug
from adgn.props.models.true_positive import SnapshotIssuesLoadError

from ._yaml_models import YAMLIssue

logger = logging.getLogger(__name__)


def load_yaml_issues(snapshot_dir: Path, snapshot_slug: SnapshotSlug) -> tuple[dict[str, dict], dict[str, dict]]:
    """Load and validate YAML issue files from a snapshot directory.

    ⚠️ SYNC PATH ONLY - use IssueData.from_db() everywhere else.

    This function reads all *.yaml files from the snapshot's issues/ subdirectory,
    validates them with Pydantic, expands to canonical models, and returns raw dicts
    ready for database insertion.

    Args:
        snapshot_dir: Snapshot directory containing an issues/ subdirectory with *.yaml files
        snapshot_slug: Snapshot slug (for model expansion)

    Returns:
        Tuple of (true_positives, false_positives) dicts.
        Each dict maps issue_id -> raw dict (with id and snapshot_slug fields).

    Raises:
        SnapshotIssuesLoadError: If loading/validation fails
    """
    if not snapshot_dir.is_dir():
        raise SnapshotIssuesLoadError([f"Snapshot directory not found: {snapshot_dir}"])

    # Discover all YAML files in the issues subdirectory
    issues_subdir = snapshot_dir / "issues"
    if not issues_subdir.is_dir():
        raise SnapshotIssuesLoadError([f"Issues subdirectory not found: {issues_subdir}"])

    yaml_files = sorted(issues_subdir.glob("*.yaml"))

    if not yaml_files:
        return {}, {}

    true_positives: dict[str, dict] = {}
    false_positives: dict[str, dict] = {}
    errors: list[str] = []

    for yaml_file in yaml_files:
        issue_id = yaml_file.stem

        try:
            # Parse YAML
            with yaml_file.open() as f:
                raw_data = yaml.safe_load(f)

            if not isinstance(raw_data, dict):
                errors.append(f"{yaml_file.name}: Expected dict, got {type(raw_data).__name__}")
                continue

            # Validate and normalize with permissive Pydantic model
            issue = YAMLIssue.model_validate(raw_data)

            # Expand to canonical form
            if issue.should_flag:
                # True positive
                tp = issue.to_true_positive(tp_id=issue_id, snapshot_slug=snapshot_slug)
                # Convert to dict for database insertion
                tp_dict = tp.model_dump()
                tp_dict["id"] = issue_id  # Add id field for consistency with Jsonnet loader
                true_positives[issue_id] = tp_dict
            else:
                # False positive
                fp = issue.to_false_positive(fp_id=issue_id, snapshot_slug=snapshot_slug)
                # Convert to dict for database insertion
                fp_dict = fp.model_dump()
                fp_dict["id"] = issue_id  # Add id field for consistency with Jsonnet loader
                false_positives[issue_id] = fp_dict

        except yaml.YAMLError as e:
            errors.append(f"{yaml_file.name}: YAML parse error: {e}")
        except ValueError as e:
            # Pydantic validation errors or model expansion errors
            errors.append(f"{yaml_file.name}: Validation error: {e}")
        except Exception as e:
            errors.append(f"{yaml_file.name}: Unexpected error: {e}")

    if errors:
        raise SnapshotIssuesLoadError(errors)

    return true_positives, false_positives
