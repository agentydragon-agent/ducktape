"""SQLAlchemy ORM models for unknowns clustering."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from adgn.props.db.models import Base, SnapshotSlugColumn
from adgn.props.ids import SnapshotSlug

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ClusteringRun(Base):
    """Top-level clustering execution record.

    Tracks agent runs that cluster unknown issues from grader runs.
    RLS-scoped via current_clustering_run_id() - agents can only see their own run.
    """

    __tablename__ = "clustering_runs"
    __table_args__ = (
        Index("ix_clustering_runs_snapshot_slug", "snapshot_slug"),
        Index("ix_clustering_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        SnapshotSlugColumn(), ForeignKey("snapshots.slug", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="in_progress")
    transcript_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default="now()")
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    # Relationships
    unknown_clusters: Mapped[list[UnknownCluster]] = relationship(
        back_populates="clustering_run", cascade="all, delete-orphan"
    )
    unknown_assignments: Mapped[list[UnknownAssignment]] = relationship(
        back_populates="clustering_run", cascade="all, delete-orphan"
    )

    @classmethod
    def get(cls, run_id: int) -> ClusteringRun | None:
        """Get clustering run by ID."""
        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return session.get(cls, run_id)

    @classmethod
    def get_for_snapshot(cls, snapshot_slug: SnapshotSlug) -> list[ClusteringRun]:
        """Get all clustering runs for a snapshot."""
        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(
            session.execute(select(cls).where(cls.snapshot_slug == snapshot_slug).order_by(cls.started_at.desc()))
            .scalars()
            .all()  # type: ignore[arg-type]
        )


class UnknownCluster(Base):
    """Named group of equivalent unknown issues.

    Clusters have kebab-case names and descriptions.
    Each cluster belongs to a clustering run.
    """

    __tablename__ = "unknown_clusters"
    __table_args__ = (Index("ix_unknown_clusters_clustering_run_id", "clustering_run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clustering_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clustering_runs.id", ondelete="CASCADE"), nullable=False
    )
    cluster_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default="now()")

    # Relationships
    clustering_run: Mapped[ClusteringRun] = relationship(back_populates="unknown_clusters")
    unknown_assignments: Mapped[list[UnknownAssignment]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )

    @classmethod
    def get(cls, cluster_id: int) -> UnknownCluster | None:
        """Get cluster by ID."""
        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return session.get(cls, cluster_id)

    @classmethod
    def get_for_run(cls, clustering_run_id: int) -> list[UnknownCluster]:
        """Get all clusters for a clustering run."""
        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(
            session.execute(select(cls).where(cls.clustering_run_id == clustering_run_id).order_by(cls.cluster_name))
            .scalars()
            .all()
        )


class UnknownAssignment(Base):
    """Assignment of unknown issue to cluster or existing TP/FP.

    Composite unique key: (clustering_run_id, grader_run_id, unknown_id, cancelled_at).
    Exactly one of (cluster_id, mapped_tp_id, mapped_fp_id) must be NOT NULL.
    Soft delete via cancelled_at preserves audit trail.
    """

    __tablename__ = "unknown_assignments"
    __table_args__ = (
        Index("ix_unknown_assignments_clustering_run_id", "clustering_run_id"),
        Index("ix_unknown_assignments_grader_run_id", "grader_run_id"),
        Index("ix_unknown_assignments_grader_unknown", "grader_run_id", "unknown_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clustering_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clustering_runs.id", ondelete="CASCADE"), nullable=False
    )
    grader_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("grader_runs.id", ondelete="CASCADE"), nullable=False
    )
    unknown_id: Mapped[str] = mapped_column(String, nullable=False)

    # Exactly one of these must be NOT NULL (enforced by CHECK constraint)
    cluster_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("unknown_clusters.id", ondelete="CASCADE"), nullable=True
    )
    # Note: mapped_tp_id/mapped_fp_id reference true_positives.tp_id/false_positives.fp_id
    # (which are part of composite PKs), but we don't use FK constraints since we'd need
    # snapshot_slug too. Application layer enforces referential integrity.
    mapped_tp_id: Mapped[str | None] = mapped_column(String, nullable=True)
    mapped_fp_id: Mapped[str | None] = mapped_column(String, nullable=True)

    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default="now()")

    # Soft delete
    cancelled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    clustering_run: Mapped[ClusteringRun] = relationship(back_populates="unknown_assignments")
    cluster: Mapped[UnknownCluster | None] = relationship(back_populates="unknown_assignments")

    @classmethod
    def get(cls, assignment_id: int) -> UnknownAssignment | None:
        """Get assignment by ID."""
        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return session.get(cls, assignment_id)

    @classmethod
    def get_active_for_run(cls, clustering_run_id: int) -> list[UnknownAssignment]:
        """Get all active (non-cancelled) assignments for a clustering run."""
        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(
            session.execute(
                select(cls)
                .where(cls.clustering_run_id == clustering_run_id, cls.cancelled_at.is_(None))
                .order_by(cls.created_at)
            )
            .scalars()
            .all()
        )

    @classmethod
    def get_for_unknown(cls, clustering_run_id: int, grader_run_id: int, unknown_id: str) -> UnknownAssignment | None:
        """Get active assignment for a specific unknown (grader_run_id, unknown_id)."""
        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return session.execute(
            select(cls).where(
                cls.clustering_run_id == clustering_run_id,
                cls.grader_run_id == grader_run_id,
                cls.unknown_id == unknown_id,
                cls.cancelled_at.is_(None),
            )
        ).scalar_one_or_none()
