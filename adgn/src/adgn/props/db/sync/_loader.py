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
from ...models.critic_scopes import ALL_FILES_WITH_ISSUES, CriticScope, CriticScopeSpec
from ...models.snapshot import Snapshot, SnapshotSlug
from ...models.training_example import TrainingExample
from ...models.true_positive import FalsePositive, TruePositive
from ...splits import Split
from ._jsonnet import evaluate_snapshot_issues

logger = logging.getLogger(__name__)


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
        raw_tps, raw_fps = evaluate_snapshot_issues(snapshot_dir)

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

        return self._create_training_example(slug, snapshot.split, targeted_files, all_tps, all_fps)

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

    @staticmethod
    def _create_training_example(
        slug: SnapshotSlug,
        split: Split,
        targeted_files: set[Path],
        all_tps: list[TruePositive],
        all_fps: list[FalsePositive],
    ) -> TrainingExample:
        """Create a TrainingExample with filtered TPs/FPs for the targeted files.

        Args:
            slug: Snapshot slug
            split: Dataset split (TRAIN, VALID, TEST)
            targeted_files: Files to review in this example
            all_tps: All true positives for the snapshot
            all_fps: All false positives for the snapshot

        Returns:
            TrainingExample with catchable TPs and relevant FPs for the targeted files
        """
        # Filter to catchable true positives
        catchable_tps = [tp for tp in all_tps if TrainingExample.should_include_tp(tp, targeted_files)]

        # Filter to relevant false positives
        relevant_fps = [fp for fp in all_fps if TrainingExample.should_include_fp(fp, targeted_files)]

        return TrainingExample(
            snapshot_slug=slug,
            split=split,
            targeted_files=frozenset(targeted_files),
            true_positives=catchable_tps,
            false_positives=relevant_fps,
        )

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
                example = self._create_training_example(slug, split, all_files, all_tps, all_fps)
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
            example = self._create_training_example(slug, snapshot.split, all_files, all_tps, all_fps)
            examples.append(example)

        return sorted(examples, key=lambda e: e.snapshot_slug)

    def load_critic_scopes(self) -> dict[SnapshotSlug, list[CriticScope]]:
        """Load specimens/critic_scopes.yaml → CriticScope objects.

        Returns:
            Dict mapping snapshot slug → list of critic scopes

        Raises:
            FileNotFoundError: If critic_scopes.yaml doesn't exist (now required)
            ValueError: If YAML is malformed or validation fails
        """
        scopes_yaml = self.specimens_dir / "critic_scopes.yaml"
        if not scopes_yaml.exists():
            raise FileNotFoundError(
                f"critic_scopes.yaml is required but not found at {scopes_yaml}. "
                "Critic scopes must be explicitly defined for all snapshots."
            )

        raw = yaml.safe_load(scopes_yaml.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"critic_scopes.yaml must contain a mapping, got {type(raw)}")

        scopes: dict[SnapshotSlug, list[CriticScope]] = {}
        for slug_str, scope_list in raw.items():
            if not isinstance(scope_list, list):
                raise ValueError(f"Scope data for '{slug_str}' must be a list, got {type(scope_list)}")

            validated_scopes = []
            for scope_data in scope_list:
                # Convert YAML format to CriticScope type
                files_raw = scope_data.get("files")
                parsed_files: CriticScopeSpec
                if files_raw == ALL_FILES_WITH_ISSUES:
                    # "all" sentinel
                    parsed_files = ALL_FILES_WITH_ISSUES
                elif isinstance(files_raw, list):
                    # List of strings -> set[Path]
                    parsed_files = {Path(f) for f in files_raw}
                else:
                    raise ValueError(f"Scope files for '{slug_str}' must be list or 'all', got {type(files_raw)}")

                scope = CriticScope(files=parsed_files)
                validated_scopes.append(scope)

            scopes[SnapshotSlug(slug_str)] = validated_scopes

        return scopes

    @staticmethod
    def _resolve_critic_scope(scope: CriticScope, all_files: set[Path], slug: SnapshotSlug) -> set[Path]:
        """Resolve a critic scope to a set of file paths.

        Args:
            scope: CriticScope to resolve
            all_files: All files with issues in the snapshot
            slug: Snapshot slug (for error messages)

        Returns:
            Resolved set of file paths

        Raises:
            ValueError: If scope references files not in the snapshot
        """
        if scope.files == ALL_FILES_WITH_ISSUES:
            return all_files.copy()
        # Type narrowing: if not ALL_FILES_WITH_ISSUES, must be set[Path]
        scope_paths = scope.files
        # Validate that scope files exist in the snapshot
        missing = scope_paths - all_files
        if missing:
            missing_str = ", ".join(str(f) for f in sorted(missing))
            raise ValueError(f"Critic scope for {slug} references files not in snapshot: {missing_str}")
        return scope_paths

    def validate_critic_scopes_coverage(self) -> None:
        """Validate that all expect_caught_from sets have corresponding scopes.

        For each true positive in all snapshots, verify that every minimal triggering
        set (expect_caught_from) has a corresponding scope defined in critic_scopes.yaml.
        This ensures we're explicitly testing detection of each issue from its minimal sets.

        Raises:
            ValueError: If any expect_caught_from sets are missing from critic_scopes.yaml
        """
        snapshots = self.load_snapshots()
        critic_scopes = self.load_critic_scopes()

        missing_scopes: dict[SnapshotSlug, list[tuple[str, frozenset[Path]]]] = {}

        for slug in snapshots:
            all_tps, _ = self.load_issues_for_snapshot(slug)
            all_files = self._collect_all_files_from_issues(all_tps, [])
            snapshot_scopes = critic_scopes.get(slug, [])

            # Build set of scope file sets for fast lookup
            # Resolve "all" sentinel and validate files exist
            scope_file_sets: set[frozenset[Path]] = set()

            for scope in snapshot_scopes:
                # Resolve scope and validate files exist
                scope_paths = self._resolve_critic_scope(scope, all_files, slug)
                scope_file_sets.add(frozenset(scope_paths))

            # Check each expect_caught_from set
            for tp in all_tps:
                for occurrence in tp.occurrences:
                    for trigger_set in occurrence.expect_caught_from:
                        trigger_frozenset = frozenset(trigger_set)

                        # Check if this exact set appears in scopes
                        if trigger_frozenset not in scope_file_sets:
                            missing_scopes.setdefault(slug, []).append((tp.tp_id, trigger_frozenset))

        if missing_scopes:
            error_lines = ["Some expect_caught_from sets are missing from critic_scopes.yaml:"]
            for slug, missing in missing_scopes.items():
                error_lines.append(f"\nSnapshot {slug}:")
                for tp_id, file_set in missing:
                    files_str = ", ".join(str(f) for f in sorted(file_set))
                    error_lines.append(f"  - TP {tp_id}: [{files_str}]")

            raise ValueError("\n".join(error_lines))

    def _generate_examples_from_scopes(
        self,
        slug: SnapshotSlug,
        split: Split,
        scopes: list[CriticScope],
        all_files: set[Path],
        all_tps: list[TruePositive],
        all_fps: list[FalsePositive],
    ) -> list[TrainingExample]:
        """Generate training examples from defined critic scopes.

        Args:
            slug: Snapshot slug
            split: Dataset split
            scopes: List of critic scopes defining file groupings
            all_files: All files with issues in the snapshot
            all_tps: All true positives for the snapshot
            all_fps: All false positives for the snapshot

        Returns:
            List of TrainingExample objects, one per scope with matching files
        """
        examples = []
        logger.debug(f"Using {len(scopes)} critic scopes for {slug}")

        for scope in scopes:
            # Resolve scope and validate files exist
            targeted_files = self._resolve_critic_scope(scope, all_files, slug)

            if targeted_files:
                example = self._create_training_example(slug, split, targeted_files, all_tps, all_fps)
                examples.append(example)
            else:
                logger.warning(f"Scope for {slug} resolved to no files")

        return examples

    def _generate_fallback_examples(
        self,
        slug: SnapshotSlug,
        split: Split,
        all_files: set[Path],
        all_tps: list[TruePositive],
        all_fps: list[FalsePositive],
    ) -> list[TrainingExample]:
        """Generate fallback per-file examples when no scopes defined.

        Args:
            slug: Snapshot slug
            split: Dataset split
            all_files: All files with issues in the snapshot
            all_tps: All true positives for the snapshot
            all_fps: All false positives for the snapshot

        Returns:
            List of TrainingExample objects, one per file
        """
        examples = []
        logger.debug(f"No critic scopes for {slug}, using per-file fallback")

        for file in sorted(all_files):
            example = self._create_training_example(slug, split, {file}, all_tps, all_fps)
            examples.append(example)

        return examples

    def get_per_file_examples_for_split(self, split: Split) -> list[TrainingExample]:
        """Get per-file training examples for a given split.

        For each snapshot in the split:
        - If critic_scopes defined: generate one TrainingExample per scope
        - If no scopes: fallback to one example per file with issues
        - Always include one full-snapshot example as the last item (terminal metric)

        Args:
            split: The split to filter by (TRAIN, VALID, or TEST)

        Returns:
            List of TrainingExample objects with focused file sets
        """
        snapshots = self.load_snapshots()
        critic_scopes = self.load_critic_scopes()
        examples = []

        for slug, snapshot in snapshots.items():
            if snapshot.split != split:
                continue

            # Load issues once per snapshot
            all_tps, all_fps = self.load_issues_for_snapshot(slug)
            all_files = self._collect_all_files_from_issues(all_tps, all_fps)

            if not all_files:
                logger.warning(f"Snapshot {slug} has no files with issues, skipping")
                continue

            # Generate focused examples (scopes or per-file fallback)
            if slug in critic_scopes:
                focused_examples = self._generate_examples_from_scopes(
                    slug, split, critic_scopes[slug], all_files, all_tps, all_fps
                )
            else:
                focused_examples = self._generate_fallback_examples(slug, split, all_files, all_tps, all_fps)

            examples.extend(focused_examples)

            # Always add full-snapshot example as terminal metric
            full_example = self._create_training_example(slug, split, all_files, all_tps, all_fps)
            examples.append(full_example)

        return examples


__all__ = ["FilesystemLoader", "TrainingExample"]
