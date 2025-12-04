"""SQLAlchemy models for properties evaluation results.

Maps to the schema defined in docs/eval_results_db.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from adgn.agent.events import EventType

T = TypeVar("T", bound=BaseModel)


class PydanticColumn(TypeDecorator[T]):
    """SQLAlchemy column type that automatically serializes/deserializes any Pydantic model.

    Usage:
        class MyModel(Base):
            data: Mapped[MyPydanticType] = mapped_column(PydanticColumn(MyPydanticType))

    Or register in type_annotation_map for automatic mapping:
        type_annotation_map = {MyPydanticType: PydanticColumn(MyPydanticType)}

    TODO: Apply this refactor to other JSONB columns in this file where appropriate.
    Candidates: fields that are currently Mapped[dict[str, Any]] but represent
    structured Pydantic models (e.g., input/output fields in CriticRun, GraderRun).
    """

    impl = JSONB
    cache_ok = True

    def __init__(self, pydantic_type: type[T]):
        super().__init__()
        self._adapter: TypeAdapter[T] = TypeAdapter(pydantic_type)

    def process_bind_param(self, value: T | None, dialect: Any) -> dict[str, Any] | None:
        """Convert Pydantic model to dict for storage (Python → DB)."""
        if value is None:
            return None
        return value.model_dump(mode="json", by_alias=True)

    def process_result_value(self, value: dict[str, Any] | None, dialect: Any) -> T | None:
        """Convert dict to Pydantic model after loading (DB → Python)."""
        if value is None:
            return None
        return self._adapter.validate_python(value)


class Base(DeclarativeBase):
    """Base class for all models."""

    type_annotation_map: ClassVar[dict[type, Any]] = {dict[str, Any]: JSONB, UUID: PG_UUID(as_uuid=True)}


class Snapshot(Base):
    """Code snapshot with split assignment.

    Source of truth for snapshot→split mapping.
    Issues/false_positives reference snapshots by slug.
    """

    __tablename__ = "snapshots"

    slug: Mapped[str] = mapped_column(String, primary_key=True)
    split: Mapped[str] = mapped_column(String, CheckConstraint("split IN ('train', 'valid', 'test')"), nullable=False)
    source: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, comment="GitSource/GitHubSource/LocalSource")
    bundle: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="BundleConfig (source_commit, include, exclude)"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    issues: Mapped[list[Issue]] = relationship(back_populates="snapshot_obj", cascade="all, delete-orphan")
    false_positives: Mapped[list[FalsePositive]] = relationship(
        back_populates="snapshot_obj", cascade="all, delete-orphan"
    )
    critic_runs: Mapped[list[CriticRun]] = relationship(back_populates="snapshot_obj")
    grader_runs: Mapped[list[GraderRun]] = relationship(back_populates="snapshot_obj")
    critiques: Mapped[list[Critique]] = relationship(back_populates="snapshot_obj")

    @classmethod
    def get(cls, slug: str) -> Snapshot | None:
        """Get snapshot by slug."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return session.execute(select(cls).where(cls.slug == slug)).scalar_one_or_none()

    @classmethod
    def get_by_split(cls, split: str) -> list[Snapshot]:
        """Get all snapshots for a split (train/valid/test)."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(session.execute(select(cls).where(cls.split == split)).scalars().all())


class Issue(Base):
    """True positive issue (expected findings).

    Composite primary key: (snapshot_slug, issue_id).
    Each issue has one or more occurrences with expect_caught_from semantics.
    """

    __tablename__ = "issues"

    snapshot_slug: Mapped[str] = mapped_column(
        String, ForeignKey("snapshots.slug", ondelete="RESTRICT"), primary_key=True
    )
    issue_id: Mapped[str] = mapped_column(String, primary_key=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, comment="IssueOccurrence objects (files, note, expect_caught_from)"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    snapshot_obj: Mapped[Snapshot] = relationship(back_populates="issues")

    @classmethod
    def get(cls, snapshot_slug: str, issue_id: str) -> Issue | None:
        """Get issue by composite key."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return session.execute(
            select(cls).where(cls.snapshot_slug == snapshot_slug, cls.issue_id == issue_id)
        ).scalar_one_or_none()

    @classmethod
    def get_for_snapshot(cls, snapshot_slug: str) -> list[Issue]:
        """Get all issues for a snapshot."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(session.execute(select(cls).where(cls.snapshot_slug == snapshot_slug)).scalars().all())


class FalsePositive(Base):
    """Known false positive (issue that looks like a problem but isn't).

    Composite primary key: (snapshot_slug, fp_id).
    Each FP has one or more occurrences with relevant_files semantics.
    """

    __tablename__ = "false_positives"

    snapshot_slug: Mapped[str] = mapped_column(
        String, ForeignKey("snapshots.slug", ondelete="RESTRICT"), primary_key=True
    )
    fp_id: Mapped[str] = mapped_column(String, primary_key=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, comment="FalsePositiveOccurrence objects (files, note, relevant_files)"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    snapshot_obj: Mapped[Snapshot] = relationship(back_populates="false_positives")

    @classmethod
    def get(cls, snapshot_slug: str, fp_id: str) -> FalsePositive | None:
        """Get false positive by composite key."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return session.execute(
            select(cls).where(cls.snapshot_slug == snapshot_slug, cls.fp_id == fp_id)
        ).scalar_one_or_none()

    @classmethod
    def get_for_snapshot(cls, snapshot_slug: str) -> list[FalsePositive]:
        """Get all false positives for a snapshot."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(session.execute(select(cls).where(cls.snapshot_slug == snapshot_slug)).scalars().all())


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
    template_file_path: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
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
    """Critique result (list of issues) for a snapshot.

    May come from a critic run (via critic_runs.critique_id FK)
    or be manually created/imported.

    Payload is always CriticSubmitPayload (from adgn.props.critic).
    """

    __tablename__ = "critiques"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    snapshot_slug: Mapped[str] = mapped_column(String, ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, comment="CriticSubmitPayload as dict")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    snapshot_obj: Mapped[Snapshot] = relationship(back_populates="critiques")
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
    snapshot_slug: Mapped[str] = mapped_column(String, ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False)
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
    snapshot_obj: Mapped[Snapshot] = relationship(back_populates="critic_runs")
    critique_obj: Mapped[Critique | None] = relationship(
        back_populates="critic_run", foreign_keys=[critique_id], post_update=True
    )
    prompt_optimization_run: Mapped[PromptOptimizationRun | None] = relationship(back_populates="critic_runs")


class GraderRun(Base):
    """Single grader run (critique + snapshot → metrics).

    No direct prompt link; linked via critique → critic_run → prompt.
    """

    __tablename__ = "grader_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    snapshot_slug: Mapped[str] = mapped_column(String, ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False)
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
    snapshot_obj: Mapped[Snapshot] = relationship(back_populates="grader_runs")
    critique_obj: Mapped[Critique] = relationship(back_populates="grader_runs")
    prompt_optimization_run: Mapped[PromptOptimizationRun | None] = relationship(back_populates="grader_runs")


class ModelMetadata(Base):
    """OpenAI model metadata: pricing, context limits, and capabilities.

    Synchronized from adgn.openai_utils.model_metadata.MODEL_METADATA via CLI.
    Enables post-hoc cost calculation and context validation in SQL.
    """

    __tablename__ = "model_metadata"

    model_id: Mapped[str] = mapped_column(String, primary_key=True)
    input_usd_per_1m_tokens: Mapped[float] = mapped_column(nullable=False)
    cached_input_usd_per_1m_tokens: Mapped[float] = mapped_column(nullable=False)
    output_usd_per_1m_tokens: Mapped[float] = mapped_column(nullable=False)
    context_window_tokens: Mapped[int] = mapped_column(nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Event(Base):
    """Agent execution event.

    Linked to critic/grader runs via shared transcript_id.

    The payload column automatically serializes/deserializes EventType via EventTypeColumn.
    Access event.payload to get a typed EventType instance, set it to store.
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
    payload: Mapped[EventType] = mapped_column(PydanticColumn(EventType), nullable=False)  # type: ignore[arg-type]
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ModelPricing(Base):
    """OpenAI model pricing and context limits (mirrors model_metadata.py).

    Synchronized from adgn.openai_utils.model_metadata.MODEL_METADATA via CLI.
    Enables post-hoc cost calculation in SQL.
    """

    __tablename__ = "model_pricing"

    model_id: Mapped[str] = mapped_column(String, primary_key=True)
    input_usd_per_1m_tokens: Mapped[float] = mapped_column(nullable=False)
    cached_input_usd_per_1m_tokens: Mapped[float] = mapped_column(nullable=False)
    output_usd_per_1m_tokens: Mapped[float] = mapped_column(nullable=False)
    context_window_tokens: Mapped[int] = mapped_column(nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )
