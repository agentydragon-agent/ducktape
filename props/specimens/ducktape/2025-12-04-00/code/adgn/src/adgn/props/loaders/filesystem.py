from __future__ import annotations

from collections.abc import Callable
import json
import logging
from pathlib import Path
from typing import Any, cast

import _jsonnet  # type: ignore[import-untyped]
import yaml

from adgn.props.models.snapshot import Snapshot, SnapshotSlug
from adgn.props.models.training_example import TrainingExample
from adgn.props.models.true_positive import FalsePositive, TruePositive
from adgn.props.splits import Split

logger = logging.getLogger(__name__)

# Shared Jsonnet library directory (same as registry.py)
JSONNET_LIBDIR = Path(__file__).resolve().parent.parent / "specimens"


def _jsonnet_importer(base: str, rel: str) -> tuple[str, bytes]:
    """Import callback for Jsonnet evaluation.

    Resolves imports relative to base path or from JSONNET_LIBDIR.
    """
    cand1 = (Path(base) / rel).resolve()
    if cand1.is_file():
        return str(cand1), cand1.read_bytes()
    rel_name = Path(rel).name
    cand2 = (JSONNET_LIBDIR / rel_name).resolve()
    if cand2.is_file():
        return str(cand2), cand2.read_bytes()
    raise RuntimeError(f"import not found: base={base!r} rel={rel!r}")


class FilesystemLoader:
    """Loads snapshot metadata and issues from filesystem.

    Responsibility: Parse YAML/Jsonnet → Pydantic objects.
    Does NOT interact with database - only reads from filesystem.
    """

    def __init__(self, specimens_dir: Path):
        """Initialize loader with specimens directory.

        Args:
            specimens_dir: Path to specimens directory (contains snapshots.yaml and snapshot subdirs)
        """
        self.specimens_dir = specimens_dir.resolve()

    def load_snapshots(self) -> dict[SnapshotSlug, Snapshot]:
        """Load specimens/snapshots.yaml → Snapshot objects.

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
        """Evaluate specimens/{slug}/*.libsonnet → Issue/FP objects.

        Determines TP vs FP by evaluating the Jsonnet and checking output structure:
        - Presence of 'expect_caught_from' in occurrences → True Positive
        - Presence of 'relevant_files' in occurrences → False Positive

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
        slug_parts = str(slug).split("/")
        if len(slug_parts) != 2:
            raise ValueError(f"Invalid snapshot slug format: {slug}. Expected 'repo/version'")

        snapshot_dir = self.specimens_dir / slug_parts[0] / slug_parts[1]
        if not snapshot_dir.is_dir():
            raise FileNotFoundError(f"Snapshot directory not found: {snapshot_dir}")

        # Find all .libsonnet files directly in snapshot directory (not in subdirs)
        issue_files = sorted(snapshot_dir.glob("*.libsonnet"))

        true_positives: list[TruePositive] = []
        false_positives: list[FalsePositive] = []

        for issue_file in issue_files:
            # Derive ID from filename stem
            file_id = issue_file.stem

            # Evaluate Jsonnet file
            try:
                eval_snippet = cast(Callable[..., Any], _jsonnet.evaluate_snippet)
                raw_json = eval_snippet(
                    str(issue_file),
                    issue_file.read_text(encoding="utf-8"),
                    jpathdir=[str(JSONNET_LIBDIR)],
                    import_callback=_jsonnet_importer,
                )
                issue_dict = json.loads(raw_json)
            except Exception as e:
                raise RuntimeError(f"Failed to evaluate {issue_file}: {e}") from e

            if not isinstance(issue_dict, dict):
                raise ValueError(f"{issue_file}: Jsonnet must return an object, got {type(issue_dict)}")

            # snapshot is auto-derived from file path (not in Jsonnet)

            # Determine if TP or FP by checking occurrence structure
            occurrences = issue_dict.get("occurrences", [])
            if not occurrences:
                raise ValueError(f"{issue_file}: No occurrences found")

            # Check first occurrence to determine type (all should be same type)
            first_occ = occurrences[0]
            is_tp = "expect_caught_from" in first_occ
            is_fp = "relevant_files" in first_occ

            if is_tp and is_fp:
                raise ValueError(
                    f"{issue_file}: Occurrence has both expect_caught_from and relevant_files. "
                    "Must be either TP (expect_caught_from) or FP (relevant_files)."
                )
            if not is_tp and not is_fp:
                raise ValueError(
                    f"{issue_file}: Occurrence missing both expect_caught_from and relevant_files. "
                    "Must have either expect_caught_from (TP) or relevant_files (FP)."
                )

            # Build model-specific dict and validate
            if is_tp:
                # True Positive
                tp_dict = {
                    "tp_id": file_id,
                    "snapshot_slug": str(slug),
                    "rationale": issue_dict["rationale"],
                    "occurrences": occurrences,
                }
                issue = TruePositive.model_validate(tp_dict)
                true_positives.append(issue)
            else:
                # False Positive
                fp_dict = {
                    "fp_id": file_id,
                    "snapshot_slug": str(slug),
                    "rationale": issue_dict["rationale"],
                    "occurrences": occurrences,
                }
                fp = FalsePositive.model_validate(fp_dict)
                false_positives.append(fp)

        return true_positives, false_positives

    def get_training_example(self, slug: SnapshotSlug, targeted_files: set[Path]) -> TrainingExample:
        """Create a focused training example for specific files in a snapshot.

        Args:
            slug: Snapshot slug (e.g., 'ducktape/2025-11-26-00')
            targeted_files: Files to review (determines which TPs/FPs are included)

        Returns:
            TrainingExample with catchable TPs and relevant FPs for the targeted files
        """
        snapshots = self.load_snapshots()
        if slug not in snapshots:
            raise KeyError(f"Snapshot '{slug}' not found in snapshots.yaml")

        snapshot = snapshots[slug]
        all_tps, all_fps = self.load_issues_for_snapshot(slug)

        # Filter to catchable true positives
        catchable_tps = [tp for tp in all_tps if TrainingExample.should_include_tp(tp, targeted_files)]

        # Filter to relevant false positives
        relevant_fps = [fp for fp in all_fps if TrainingExample.should_include_fp(fp, targeted_files)]

        return TrainingExample(
            snapshot_slug=slug,
            split=snapshot.split,
            targeted_files=frozenset(targeted_files),
            true_positives=catchable_tps,
            false_positives=relevant_fps,
        )

    @staticmethod
    def _collect_all_files_from_issues(
        true_positives: list[TruePositive], false_positives: list[FalsePositive]
    ) -> set[Path]:
        """Collect all files referenced in true positives and false positives.

        Args:
            true_positives: List of true positive issues
            false_positives: List of false positive issues

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

    def get_examples_for_split(self, split: Split) -> list[TrainingExample]:
        """Get training examples for a given split (full snapshot review).

        Each example targets ALL files in the snapshot (full review scenario).
        For focused file subsets, use get_training_example(slug, targeted_files).

        Args:
            split: The split to filter by (TRAIN, VALID, or TEST)

        Returns:
            List of TrainingExample objects for snapshots in the given split
        """
        snapshots = self.load_snapshots()
        examples = []

        for slug, snapshot in snapshots.items():
            if snapshot.split == split:
                all_tps, all_fps = self.load_issues_for_snapshot(slug)
                all_files = self._collect_all_files_from_issues(all_tps, all_fps)

                # Create example targeting all files (full snapshot review)
                example = TrainingExample(
                    snapshot_slug=slug,
                    split=split,
                    targeted_files=frozenset(all_files),
                    true_positives=all_tps,
                    false_positives=all_fps,
                )
                examples.append(example)

        return sorted(examples, key=lambda e: e.snapshot_slug)

    def get_all_examples(self) -> list[TrainingExample]:
        """Get all training examples across all splits (full snapshot review).

        Each example targets ALL files in the snapshot (full review scenario).
        For focused file subsets, use get_training_example(slug, targeted_files).

        Returns:
            List of all TrainingExample objects, sorted by slug
        """
        snapshots = self.load_snapshots()
        examples = []

        for slug, snapshot in snapshots.items():
            all_tps, all_fps = self.load_issues_for_snapshot(slug)
            all_files = self._collect_all_files_from_issues(all_tps, all_fps)

            # Create example targeting all files (full snapshot review)
            example = TrainingExample(
                snapshot_slug=slug,
                split=snapshot.split,
                targeted_files=frozenset(all_files),
                true_positives=all_tps,
                false_positives=all_fps,
            )
            examples.append(example)

        return sorted(examples, key=lambda e: e.snapshot_slug)


__all__ = ["FilesystemLoader", "TrainingExample"]
