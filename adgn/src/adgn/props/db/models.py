"""SQLAlchemy models for properties evaluation results.

Maps to the schema defined in docs/eval_results_db.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    type_annotation_map: ClassVar[dict[type, Any]] = {dict[str, Any]: JSONB, UUID: PG_UUID(as_uuid=True)}


class Specimen(Base):
    """Specimen with its split assignment and known files.

    Single source of truth for specimen→split mapping and file lists.
    """

    __tablename__ = "specimens"

    specimen_slug: Mapped[str] = mapped_column("specimen", String, primary_key=True)
    split: Mapped[str] = mapped_column(String, CheckConstraint("split IN ('train', 'valid', 'test')"), nullable=False)
    labeled_files: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
        comment="Files referenced in ground truth issue definitions (TPs and FPs). Used for critic scope validation.",
    )

    # Relationships
    critic_runs: Mapped[list[CriticRun]] = relationship(back_populates="specimen_obj", cascade="all, delete-orphan")
    grader_runs: Mapped[list[GraderRun]] = relationship(back_populates="specimen_obj", cascade="all, delete-orphan")
    critiques: Mapped[list[Critique]] = relationship(back_populates="specimen_obj", cascade="all, delete-orphan")


class Prompt(Base):
    """Critic prompt template identified by SHA256 hash."""

    __tablename__ = "prompts"

    prompt_sha256: Mapped[str] = mapped_column("prompt_sha256", String(64), primary_key=True)
    # prompt_text has no unique constraint: PostgreSQL btree indexes can't handle values >2.7KB
    # (1/3 of 8KB page). Uniqueness is enforced via prompt_sha256 primary key instead.
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_optimization_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("prompt_optimization_runs.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    critic_runs: Mapped[list[CriticRun]] = relationship(back_populates="prompt_obj")
    prompt_optimization_run: Mapped[PromptOptimizationRun | None] = relationship(back_populates="prompts")


class PromptOptimizationRun(Base):
    """Prompt optimization session grouping related critic/grader runs.

    TODO: Add status tracking (running/completed/failed/budget_exceeded).
    TODO: Integrate with prompt_optimizer.py to create and update runs.
    """

    __tablename__ = "prompt_optimization_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    transcript_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, unique=True, index=True)
    budget_limit: Mapped[float] = mapped_column(nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    prompts: Mapped[list[Prompt]] = relationship(back_populates="prompt_optimization_run")
    critic_runs: Mapped[list[CriticRun]] = relationship(back_populates="prompt_optimization_run")
    grader_runs: Mapped[list[GraderRun]] = relationship(back_populates="prompt_optimization_run")


class Critique(Base):
    """Critique result (list of issues) for a specimen.

    May come from a critic run (via critic_runs.critique_id FK)
    or be manually created/imported.

    Payload is always CriticSubmitPayload (from adgn.props.critic).
    """

    __tablename__ = "critiques"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    specimen_slug: Mapped[str] = mapped_column("specimen", String, ForeignKey("specimens.specimen"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, comment="CriticSubmitPayload as dict")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    specimen_obj: Mapped[Specimen] = relationship(back_populates="critiques")
    critic_run: Mapped[CriticRun | None] = relationship(
        back_populates="critique_obj", foreign_keys="CriticRun.critique_id"
    )
    grader_runs: Mapped[list[GraderRun]] = relationship(back_populates="critique_obj")


class CriticRun(Base):
    """Single critic run (code → candidate issues).

    Links to the critique it produced (if successful).
    """

    __tablename__ = "critic_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    prompt_sha256: Mapped[str] = mapped_column(String(64), ForeignKey("prompts.prompt_sha256"), nullable=False)
    specimen_slug: Mapped[str] = mapped_column("specimen", String, ForeignKey("specimens.specimen"), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    critique_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("critiques.id"), nullable=True)
    prompt_optimization_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("prompt_optimization_runs.id"), nullable=True, index=True
    )
    files: Mapped[list[str]] = mapped_column(JSONB, nullable=False, comment="Files in critic scope")
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    prompt_obj: Mapped[Prompt] = relationship(back_populates="critic_runs")
    specimen_obj: Mapped[Specimen] = relationship(back_populates="critic_runs")
    critique_obj: Mapped[Critique | None] = relationship(
        back_populates="critic_run", foreign_keys=[critique_id], post_update=True
    )
    prompt_optimization_run: Mapped[PromptOptimizationRun | None] = relationship(back_populates="critic_runs")


class GraderRun(Base):
    """Single grader run (critique + specimen → metrics).

    No direct prompt link; linked via critique → critic_run → prompt.
    """

    __tablename__ = "grader_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    specimen_slug: Mapped[str] = mapped_column("specimen", String, ForeignKey("specimens.specimen"), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    critique_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("critiques.id"), nullable=False)
    prompt_optimization_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("prompt_optimization_runs.id"), nullable=True, index=True
    )
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    specimen_obj: Mapped[Specimen] = relationship(back_populates="grader_runs")
    critique_obj: Mapped[Critique] = relationship(back_populates="grader_runs")
    prompt_optimization_run: Mapped[PromptOptimizationRun | None] = relationship(back_populates="grader_runs")


class Event(Base):
    """Agent execution event.

    Linked to critic/grader runs via shared transcript_id.
    """

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("transcript_id", "sequence_num", name="uq_events_transcript_id_seq"),
        Index("ix_events_transcript_id_seq", "transcript_id", "sequence_num"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transcript_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sequence_num: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )
