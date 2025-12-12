"""Filesystem loader for sync operations.

⚠️⚠️⚠️ PRIVATE MODULE - DO NOT IMPORT OUTSIDE db/sync/ ⚠️⚠️⚠️

This module is part of the sync machinery. It evaluates jsonnet files and returns
Pydantic models for database insertion.

For runtime issue loading, use ORM models:
    session = get_session()
    snapshot = session.query(Snapshot).filter_by(slug=slug).one()
    tps = snapshot.true_positives  # ORM relationship

See docs/plans/decouple-hydration-from-issue-loading.md for architecture details.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ...ids import split_snapshot_slug
from ...models.snapshot import Snapshot, SnapshotSlug
from ._jsonnet import evaluate_snapshot_issues
from ._models import FalsePositive, TruePositive

logger = logging.getLogger(__name__)


class FilesystemLoader:
    """Loads snapshot metadata and issues from filesystem for sync operations.

    ONLY used during sync: Jsonnet → Pydantic → ORM → Database.
    For training examples, query the database directly using ORM models.
    """

    def __init__(self, specimens_dir: Path):
        """Initialize loader with specimens directory.

        Args:
            specimens_dir: Path to specimens directory (contains snapshots.yaml and snapshot subdirs)
        """
        self.specimens_dir = specimens_dir.resolve()

    def load_snapshots(self) -> dict[SnapshotSlug, Snapshot]:
        """Load snapshots.yaml → Snapshot objects.

        Returns:
            Dict mapping snapshot slug → validated Snapshot objects

        Raises:
            FileNotFoundError: If snapshots.yaml doesn't exist
            ValueError: If YAML is malformed or validation fails
        """
        snapshots_yaml = self.specimens_dir / "snapshots.yaml"
        if not snapshots_yaml.exists():
            raise FileNotFoundError(f"snapshots.yaml not found at {snapshots_yaml}")

        raw = yaml.safe_load(snapshots_yaml.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"snapshots.yaml must contain a mapping, got {type(raw)}")

        snapshots: dict[SnapshotSlug, Snapshot] = {}
        for slug_str, snapshot_data in raw.items():
            if not isinstance(snapshot_data, dict):
                raise ValueError(f"Snapshot data for '{slug_str}' must be a mapping, got {type(snapshot_data)}")

            # Add slug to data for validation
            snapshot_data["slug"] = slug_str
            snapshot = Snapshot.model_validate(snapshot_data)
            snapshots[SnapshotSlug(slug_str)] = snapshot

        return snapshots

    def load_issues_for_snapshot(self, slug: SnapshotSlug) -> tuple[list[TruePositive], list[FalsePositive]]:
        """Evaluate specimens/{slug}/issues/*.libsonnet → Issue/FP objects.

        Uses batch evaluation from _jsonnet.evaluate_snapshot_issues() which handles
        TP/FP splitting based on occurrence structure.

        Args:
            slug: Snapshot slug (e.g., 'ducktape/2025-11-26-00')

        Returns:
            Tuple of (issues, false_positives) with validated Pydantic models

        Raises:
            FileNotFoundError: If snapshot directory doesn't exist
            RuntimeError: If Jsonnet evaluation fails
            ValueError: If validation fails
        """
        # Convert slug to path: "ducktape/2025-11-26-00" → "specimens/ducktape/2025-11-26-00"
        repo, version = split_snapshot_slug(slug)
        snapshot_dir = self.specimens_dir / repo / version
        if not snapshot_dir.is_dir():
            raise FileNotFoundError(f"Snapshot directory not found: {snapshot_dir}")

        # Batch-evaluate all issues (returns dicts with IDs already injected)
        raw_tps, raw_fps = evaluate_snapshot_issues(snapshot_dir, self.specimens_dir)

        # Convert to Pydantic models with proper instantiation
        return (
            [
                TruePositive(
                    tp_id=issue_id,
                    snapshot_slug=slug,
                    rationale=issue_dict["rationale"],
                    occurrences=issue_dict["occurrences"],
                )
                for issue_id, issue_dict in raw_tps.items()
            ],
            [
                FalsePositive(
                    fp_id=fp_id, snapshot_slug=slug, rationale=fp_dict["rationale"], occurrences=fp_dict["occurrences"]
                )
                for fp_id, fp_dict in raw_fps.items()
            ],
        )

    @staticmethod
    def _collect_all_files_from_issues(
        true_positives: list[TruePositive], false_positives: list[FalsePositive]
    ) -> set[Path]:
        """Collect all files referenced in true positives and false positives.

        Used during sync for validation and data quality checks.

        Args:
            true_positives: List of true positive issues (Pydantic, from Jsonnet)
            false_positives: List of false positive issues (Pydantic, from Jsonnet)

        Returns:
            Set of all file paths referenced in any occurrence
        """
        all_files: set[Path] = set()
        for tp in true_positives:
            for tp_occ in tp.occurrences:
                all_files.update(tp_occ.files.keys())
        for fp in false_positives:
            for fp_occ in fp.occurrences:
                all_files.update(fp_occ.files.keys())
        return all_files


__all__ = ["FilesystemLoader"]
