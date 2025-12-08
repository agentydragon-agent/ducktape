"""Shared logic for loading training examples across splits.

This module provides the single source of truth for how training examples
are filtered and counted across train/valid/test splits.

GEPA's loading logic:
- TRAIN: All critic scopes (per-file + full-specimen for tighter feedback loops)
- VALID/TEST: Only full-specimen scopes (terminal metric - comprehensive review)
"""

from __future__ import annotations

from itertools import chain

from sqlalchemy.orm import Session

from adgn.props.db.models import Snapshot
from adgn.props.gepa.models import SnapshotInput
from adgn.props.models.critic_scopes import AllFilesScope, CriticScopeSpec, ExplicitFileScope
from adgn.props.splits import Split


def count_available_examples_for_split(session: Session, split: Split) -> int:
    """Count available training examples for a split, matching GEPA's loading logic.

    Args:
        session: SQLAlchemy session
        split: Split to count examples for

    Returns:
        Number of training examples available for this split
    """
    snapshots = session.query(Snapshot).filter_by(split=split).all()

    if split == Split.TRAIN:
        # Train: count ALL critic scopes (per-file + full-specimen)
        return sum(len(snapshot.critic_scopes) for snapshot in snapshots)
    # Valid/Test: count only full-specimen scopes
    full_specimen_scopes = [
        scope for snapshot in snapshots for scope in snapshot.critic_scopes if snapshot.is_full_specimen_scope(scope)
    ]
    return len(full_specimen_scopes)


def _build_snapshot_datapoints(snapshot: Snapshot, filter_to_full_specimen: bool = False) -> list[SnapshotInput]:
    """Build SnapshotInput datapoints from a Snapshot ORM object using critic scopes.

    Requires critic scopes to be defined in database (sync validation ensures this).

    Args:
        snapshot: Snapshot ORM object with relationships loaded
        filter_to_full_specimen: If True, only include full-specimen scopes
                                 (used for validation/test sets)

    Returns:
        List of SnapshotInput objects (one per critic scope, filtered if requested)

    Raises:
        ValueError: If snapshot has no critic scopes
    """
    if not snapshot.critic_scopes:
        raise ValueError(f"Snapshot {snapshot.slug} has no critic scopes")

    inputs: list[SnapshotInput] = []

    # Generate one SnapshotInput per critic scope
    for scope_db in snapshot.critic_scopes:
        # Check if this scope is full-specimen
        is_full_specimen = snapshot.is_full_specimen_scope(scope_db)

        # Skip per-file scopes if filtering to full-specimen only
        if filter_to_full_specimen and not is_full_specimen:
            continue

        # Construct appropriate CriticScopeSpec
        if is_full_specimen:
            target_files: CriticScopeSpec = AllFilesScope()
        else:
            target_files = ExplicitFileScope(files=scope_db.files)

        # files_hash is precomputed during sync (from resolved files)
        inputs.append(SnapshotInput(slug=snapshot.slug, target_files=target_files, files_hash=scope_db.files_hash))

    return inputs


def get_datapoints_for_split(session: Session, split: Split) -> list[SnapshotInput]:
    """Get all training datapoints for a split.

    This is the main entrypoint for loading training examples. Returns SnapshotInput
    datapoints ready for evaluation, with proper filtering based on split type.

    CRITICAL: Dataset Order Determinism
    ------------------------------------
    GEPA's ListDataLoader uses list indices as DataIds (0, 1, 2, ...).
    Snapshots are ordered by slug (deterministic), and critic scopes within
    each snapshot are ordered by id (auto-increment). This ensures consistent
    ordering across all runs for checkpoint compatibility.

    Args:
        session: SQLAlchemy session
        split: Split to load (TRAIN, VALID, or TEST)

    Returns:
        List of SnapshotInput datapoints, ordered deterministically:
        - TRAIN: All critic scopes (per-file + full-specimen)
        - VALID/TEST: Only full-specimen scopes (terminal metric)

    Raises:
        ValueError: If any snapshot has no critic scopes
    """
    # Load snapshots in deterministic order (by slug)
    snapshots = session.query(Snapshot).filter_by(split=split).order_by(Snapshot.slug).all()

    # Determine filtering based on split type
    # Train: use all scopes (per-file + full-specimen for tighter feedback loops)
    # Valid/Test: only full-specimen scopes (terminal metric - comprehensive review)
    filter_to_full_specimen = split != Split.TRAIN

    # Build datapoints from all snapshots
    # Critic scopes are ordered by id within each snapshot (see Snapshot.critic_scopes relationship)
    return list(chain.from_iterable(_build_snapshot_datapoints(s, filter_to_full_specimen) for s in snapshots))
