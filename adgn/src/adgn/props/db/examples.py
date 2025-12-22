"""Example model and scope-based training example identification.

Examples define training/evaluation scopes (per-file or whole-snapshot).
Content-addressed by scope_hash for natural deduplication.

Scope hashing is an internal implementation detail - external code should
use Example.from_scope() or Example.from_explicit_files() constructors.

This module also provides shared logic for loading training examples across splits
(train/valid/test), which is the single source of truth for GEPA and other optimizers.
"""

from __future__ import annotations

from datetime import datetime
import hashlib

import canonicaljson
from pydantic import TypeAdapter
from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from adgn.props.db.models import Base, PydanticColumn, Snapshot, SnapshotSlugColumn
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, CriticScopeSpec, ExplicitFileScope, ScopeKind
from adgn.props.splits import Split

# =============================================================================
# Private Implementation Detail: Scope Hashing
# =============================================================================


def _compute_scope_hash(scope: CriticScopeSpec) -> str:
    """Compute SHA256 hash of canonical JSON representation of scope.

    INTERNAL IMPLEMENTATION DETAIL - DO NOT CALL DIRECTLY.
    Use Example.from_scope() or Example.from_explicit_files() instead.

    Args:
        scope: The critic scope specification (AllFilesScope | ExplicitFileScope)

    Returns:
        64-character hexadecimal SHA256 hash string
    """
    adapter: TypeAdapter[CriticScopeSpec] = TypeAdapter(CriticScopeSpec)
    # Dump to JSON dict (use alias names for consistency)
    scope_dict = adapter.dump_python(scope, mode="json", by_alias=True)
    # Encode as canonical JSON (deterministic field ordering, no whitespace)
    canonical_bytes = canonicaljson.encode_canonical_json(scope_dict)
    # Compute SHA256 hash
    return hashlib.sha256(canonical_bytes).hexdigest()


# =============================================================================
# Example Model
# =============================================================================


class Example(Base):
    """Training/evaluation examples - single source of truth for critic scopes.

    Each example defines a specific scope to evaluate (AllFilesScope or ExplicitFileScope).
    Examples are content-addressed by scope_hash for natural deduplication.

    Auto-generated from expect_caught_from data at db sync time.
    See docs/training_strategy.md for details on example generation.

    Construction:
        Use class methods rather than direct instantiation:
        - Example.from_scope(snapshot_slug, scope)
        - Example.from_explicit_files(snapshot_slug, files)
        - Example.from_all_files(snapshot_slug)

    TODO: Add n_catchable_occurrences column (property of example, not grader run).
        Problem: Current views compute catchable occurrences from grading_decisions,
        which only exist when grader runs complete. This creates ambiguity:
        - Failed critic runs (no grader) → n_catchable = 0 → recall = NULL (wrong, should be 0/N)
        - No critic runs at all → n_catchable = 0 → recall = NULL (correct)
        Solution: Compute catchable occurrences once per example (from true_positives +
        scope) and store in examples table. Views can then distinguish:
        - recall = 0.0 when caught=0, n_catchable=N (all runs failed)
        - recall = NULL when n_examples=0 (no runs exist)
    """

    __tablename__ = "examples"
    __table_args__ = ()

    # Composite primary key: (snapshot_slug, scope_hash)
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        SnapshotSlugColumn(), ForeignKey("snapshots.slug", ondelete="CASCADE"), primary_key=True
    )
    scope_hash: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="SHA256 hash of canonical JSON scope structure"
    )

    # Scope specification (discriminated union: AllFilesScope | ExplicitFileScope)
    scope: Mapped[CriticScopeSpec] = mapped_column(
        PydanticColumn(CriticScopeSpec),
        nullable=False,
        comment="Critic scope spec (discriminated union). NO resolved file lists stored.",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships - use string references to avoid circular imports
    snapshot_obj: Mapped[Snapshot] = relationship("Snapshot", foreign_keys=[snapshot_slug], back_populates="examples")
    # Note: CriticRun relationship removed - AgentRun stores snapshot_slug/scope_hash in JSONB type_config,
    # so there's no direct FK relationship possible. Query AgentRun via type_config filtering instead.

    @classmethod
    def from_scope(cls, snapshot_slug: SnapshotSlug, scope: AllFilesScope | ExplicitFileScope) -> Example:
        """Create Example from a scope.

        Automatically computes scope_hash from the scope.

        Args:
            snapshot_slug: Snapshot slug
            scope: Critic scope (AllFilesScope or ExplicitFileScope)

        Returns:
            Example with computed scope_hash
        """
        scope_hash = _compute_scope_hash(scope)
        return cls(snapshot_slug=snapshot_slug, scope_hash=scope_hash, scope=scope)

    @classmethod
    def from_explicit_files(cls, snapshot_slug: SnapshotSlug, files: list[str]) -> Example:
        """Create Example from explicit file list.

        Automatically computes scope_hash from the scope.

        Args:
            snapshot_slug: Snapshot slug
            files: List of file paths (strings)

        Returns:
            Example with computed scope_hash
        """
        scope = ExplicitFileScope(files=files)
        return cls.from_scope(snapshot_slug, scope)

    @classmethod
    def from_all_files(cls, snapshot_slug: SnapshotSlug) -> Example:
        """Create Example for whole-snapshot (all files) scope.

        Automatically computes scope_hash from AllFilesScope.

        Args:
            snapshot_slug: Snapshot slug

        Returns:
            Example with computed scope_hash
        """
        scope = AllFilesScope()
        return cls.from_scope(snapshot_slug, scope)


# =============================================================================
# Training Example Loading (GEPA Integration)
# =============================================================================


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


def count_available_examples_by_scope_all(session: Session, splits: list[Split]) -> dict[tuple[Split, ScopeKind], int]:
    """Count examples grouped by split and scope kind.

    Args:
        session: SQLAlchemy session
        splits: List of splits to count examples for

    Returns:
        Dict mapping (split, scope_kind) to count, ordered by split then scope_kind.
    """
    # Extract scope kind from JSONB: scope->>'kind'
    scope_kind = Example.scope["kind"].astext

    results = (
        session.query(Snapshot.split, scope_kind, func.count(Example.snapshot_slug))
        .join(Snapshot, Snapshot.slug == Example.snapshot_slug)
        .where(Snapshot.split.in_(splits))
        .group_by(Snapshot.split, scope_kind)
        .order_by(Snapshot.split, scope_kind)
        .all()
    )
    # Build ordered dict (Python 3.7+ preserves insertion order)
    return {(split, ScopeKind(kind_str)): count for split, kind_str, count in results}


def get_examples_for_split(session: Session, split: Split) -> list[Example]:
    """Get all training examples for a split.

    This is the main entrypoint for loading training examples. Returns Example objects
    ready for evaluation by querying the Examples table directly.

    CRITICAL: Dataset Order Determinism
    ------------------------------------
    GEPA's ListDataLoader uses list indices as DataIds (0, 1, 2, ...).
    Examples are ordered by (snapshot_slug, scope_hash) for deterministic ordering
    across all runs, ensuring checkpoint compatibility.

    Args:
        session: SQLAlchemy session
        split: Split to load (TRAIN, VALID, or TEST)

    Returns:
        List of Example objects, ordered deterministically:
        - TRAIN: All examples (per-file + full-specimen for tighter feedback loops)
        - VALID/TEST: Full-specimen examples only (ensured by db sync at example generation time)

        Examples are detached from the session (via expunge) so they can be used
        as value objects outside the session context.

    Note:
        Example filtering (per-file vs full-specimen) is handled at db sync time.
        This function trusts that the Examples table contains the correct examples for each split.
    """
    # Query examples directly with join to filter by split
    # Order by (snapshot_slug, scope_hash) for deterministic ordering
    examples = (
        session.query(Example)
        .join(Snapshot, Snapshot.slug == Example.snapshot_slug)
        .where(Snapshot.split == split)
        .order_by(Example.snapshot_slug, Example.scope_hash)
        .all()
    )

    # Detach from session so they can be used as value objects
    for example in examples:
        session.expunge(example)

    return examples


__all__ = [
    "Example",
    "count_available_examples_by_scope_all",
    "count_available_examples_for_split",
    "get_examples_for_split",
]
