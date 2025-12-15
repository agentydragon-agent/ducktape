"""Shared logic for loading training examples across splits.

This module provides the single source of truth for how training examples
are filtered and counted across train/valid/test splits.

GEPA's loading logic:
- TRAIN: All examples (per-file + full-specimen for tighter feedback loops)
- VALID/TEST: Only full-specimen examples (terminal metric - comprehensive review)

Examples are stored in the Examples table with their snapshot_slug and files list.
This module queries Examples directly rather than loading Snapshot ORM objects.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from adgn.props.db.models import Example, Snapshot
from adgn.props.gepa.models import SnapshotInput
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope
from adgn.props.splits import Split


def count_available_examples_for_split(session: Session, split: Split) -> int:
    """Count available training examples for a split, matching GEPA's loading logic.

    Args:
        session: SQLAlchemy session
        split: Split to count examples for

    Returns:
        Number of training examples available for this split

    Note:
        Validation/test snapshots should have exactly one example each (full-specimen).
        This count trusts that db sync created the right examples.
    """
    # Count examples efficiently with a join
    count = (
        session.query(func.count(Example.snapshot_slug))
        .join(Snapshot, Snapshot.slug == Example.snapshot_slug)
        .where(Snapshot.split == split)
        .scalar()
    )
    return count or 0


def count_available_examples_by_scope(session: Session, split: Split, is_whole_snapshot: bool) -> int:
    """Count available training examples for a split and scope.

    Args:
        session: SQLAlchemy session
        split: Split to count examples for
        is_whole_snapshot: If True, count only whole-snapshot examples; if False, count only partial examples

    Returns:
        Number of training examples matching the criteria
    """
    count = (
        session.query(func.count(Example.snapshot_slug))
        .join(Snapshot, Snapshot.slug == Example.snapshot_slug)
        .where(Snapshot.split == split, Example.is_whole_snapshot == is_whole_snapshot)
        .scalar()
    )
    return count or 0


def get_examples_for_split(session: Session, split: Split) -> list[SnapshotInput]:
    """Get all training examples for a split.

    This is the main entrypoint for loading training examples. Returns SnapshotInput
    examples ready for evaluation by querying the Examples table directly.

    CRITICAL: Dataset Order Determinism
    ------------------------------------
    GEPA's ListDataLoader uses list indices as DataIds (0, 1, 2, ...).
    Examples are ordered by (snapshot_slug, files_hash) for deterministic ordering
    across all runs, ensuring checkpoint compatibility.

    Args:
        session: SQLAlchemy session
        split: Split to load (TRAIN, VALID, or TEST)

    Returns:
        List of SnapshotInput examples, ordered deterministically:
        - TRAIN: All examples (per-file + full-specimen for tighter feedback loops)
        - VALID/TEST: Full-specimen examples only (ensured by db sync at example generation time)

    Note:
        Example filtering (per-file vs full-specimen) is handled at db sync time.
        This function trusts that the Examples table contains the correct examples for each split.
    """
    # Query examples directly with join to filter by split
    # Order by (snapshot_slug, files_hash) for deterministic ordering
    examples = (
        session.query(Example)
        .join(Snapshot, Snapshot.slug == Example.snapshot_slug)
        .where(Snapshot.split == split)
        .order_by(Example.snapshot_slug, Example.files_hash)
        .all()
    )

    # Convert Example rows to SnapshotInput objects
    return [
        SnapshotInput(
            slug=example.snapshot_slug,
            target_files=(
                AllFilesScope() if example.is_whole_snapshot else ExplicitFileScope(files=example.files or [])
            ),
            files_hash=example.files_hash,
        )
        for example in examples
    ]
