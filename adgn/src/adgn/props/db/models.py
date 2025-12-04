"""SQLAlchemy models for properties evaluation results.

Maps to the schema defined in docs/eval_results_db.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    cast,
    event,
    func,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.schema import DDL
from sqlalchemy.types import TypeDecorator

from adgn.agent.events import EventType
from adgn.props.ids import SnapshotSlug, _SnapshotSlugBase
from adgn.props.models.snapshot import BundleFilter, Source

T = TypeVar("T", bound=BaseModel)


class PydanticColumn(TypeDecorator[T]):
    """SQLAlchemy column type that automatically serializes/deserializes any Pydantic model.

    Usage:
        class MyModel(Base):
            data: Mapped[MyPydanticType] = mapped_column(PydanticColumn(MyPydanticType))

    Or register in type_annotation_map for automatic mapping:
        type_annotation_map = {MyPydanticType: PydanticColumn(MyPydanticType)}

    For union types or TypeAliases, pass the type directly (not as a class):
        source: Mapped[Source] = mapped_column(PydanticColumn(Source))

    TODO: Apply this refactor to other JSONB columns in this file where appropriate.
    Candidates: fields that are currently Mapped[dict[str, Any]] but represent
    structured Pydantic models (e.g., input/output fields in CriticRun, GraderRun).
    """

    impl = JSONB
    cache_ok = True

    def __init__(self, pydantic_type: type[T] | Any):
        """Initialize with a Pydantic type or TypeAlias.

        Args:
            pydantic_type: Can be a Pydantic BaseModel class, or a TypeAlias like Source
        """
        super().__init__()
        self._adapter: TypeAdapter[T] = TypeAdapter(pydantic_type)

    def process_bind_param(self, value: T | None, dialect: Any) -> dict[str, Any] | None:
        """Convert Pydantic model to dict for storage (Python → DB)."""
        if value is None:
            return None
        # Use TypeAdapter.dump_python for all types (handles BaseModel and unions)
        return self._adapter.dump_python(value, mode="json", by_alias=True)  # type: ignore[no-any-return]

    def process_result_value(self, value: dict[str, Any] | None, dialect: Any) -> T | None:
        """Convert dict to Pydantic model after loading (DB → Python)."""
        if value is None:
            return None
        return self._adapter.validate_python(value)


class SnapshotSlugColumn(TypeDecorator[SnapshotSlug]):
    """SQLAlchemy column type for SnapshotSlug.

    Stores as String in DB, validates and wraps as SnapshotSlug on load.
    """

    impl = String
    cache_ok = True

    def __init__(self):
        super().__init__()
        self._adapter: TypeAdapter[_SnapshotSlugBase] = TypeAdapter(_SnapshotSlugBase)

    def process_bind_param(self, value: SnapshotSlug | str | None, dialect: Any) -> str | None:
        """Convert SnapshotSlug to string for storage (Python → DB)."""
        if value is None:
            return None
        # SnapshotSlug is a NewType over validated string, so it's already a string at runtime
        return str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> SnapshotSlug | None:
        """Convert string to SnapshotSlug after loading (DB → Python)."""
        if value is None:
            return None
        # Validate and wrap in NewType
        validated = self._adapter.validate_python(value)
        return SnapshotSlug(validated)


class Base(DeclarativeBase):
    """Base class for all models."""

    type_annotation_map: ClassVar[dict[type, Any]] = {
        dict[str, Any]: JSONB,
        UUID: PG_UUID(as_uuid=True),
        SnapshotSlug: SnapshotSlugColumn(),
    }


class Snapshot(Base):
    """Code snapshot with split assignment.

    Source of truth for snapshot→split mapping.
    Issues/false_positives reference snapshots by slug.
    """

    __tablename__ = "snapshots"

    slug: Mapped[SnapshotSlug] = mapped_column(primary_key=True)
    split: Mapped[str] = mapped_column(String, CheckConstraint("split IN ('train', 'valid', 'test')"), nullable=False)
    source: Mapped[Source] = mapped_column(PydanticColumn(Source), nullable=False)
    bundle: Mapped[BundleFilter | None] = mapped_column(PydanticColumn(BundleFilter), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    true_positives: Mapped[list[TruePositive]] = relationship(
        back_populates="snapshot_obj", cascade="all, delete-orphan"
    )
    false_positives: Mapped[list[FalsePositive]] = relationship(
        back_populates="snapshot_obj", cascade="all, delete-orphan"
    )
    critic_runs: Mapped[list[CriticRun]] = relationship(back_populates="snapshot_obj")
    grader_runs: Mapped[list[GraderRun]] = relationship(back_populates="snapshot_obj")
    critiques: Mapped[list[Critique]] = relationship(back_populates="snapshot_obj")

    @classmethod
    def get(cls, slug: SnapshotSlug) -> Snapshot | None:
        """Get snapshot by slug."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        # str() needed for mypy compatibility with SQLAlchemy comparison operators
        return session.execute(select(cls).where(cls.slug == str(slug))).scalar_one_or_none()

    @classmethod
    def get_by_split(cls, split: str) -> list[Snapshot]:
        """Get all snapshots for a split (train/valid/test)."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(session.execute(select(cls).where(cls.split == split)).scalars().all())


class TruePositive(Base):
    """True positive (expected findings).

    Composite primary key: (snapshot_slug, tp_id).
    Each true positive has one or more occurrences with expect_caught_from semantics.
    """

    __tablename__ = "true_positives"

    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        ForeignKey("snapshots.slug", ondelete="RESTRICT"), primary_key=True
    )
    tp_id: Mapped[str] = mapped_column(String, primary_key=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, comment="TruePositiveOccurrence objects (files, note, expect_caught_from)"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    snapshot_obj: Mapped[Snapshot] = relationship(back_populates="true_positives")

    @classmethod
    def get(cls, snapshot_slug: SnapshotSlug, tp_id: str) -> TruePositive | None:
        """Get true positive by composite key."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        # str() needed for mypy compatibility with SQLAlchemy comparison operators
        return session.execute(
            select(cls).where(cls.snapshot_slug == str(snapshot_slug), cls.tp_id == tp_id)
        ).scalar_one_or_none()

    @classmethod
    def get_for_snapshot(cls, snapshot_slug: SnapshotSlug) -> list[TruePositive]:
        """Get all true positives for a snapshot."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        # str() needed for mypy compatibility with SQLAlchemy comparison operators
        return list(session.execute(select(cls).where(cls.snapshot_slug == str(snapshot_slug))).scalars().all())


class FalsePositive(Base):
    """Known false positive (issue that looks like a problem but isn't).

    Composite primary key: (snapshot_slug, fp_id).
    Each FP has one or more occurrences with relevant_files semantics.
    """

    __tablename__ = "false_positives"

    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        ForeignKey("snapshots.slug", ondelete="RESTRICT"), primary_key=True
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
    def get(cls, snapshot_slug: SnapshotSlug, fp_id: str) -> FalsePositive | None:
        """Get false positive by composite key."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        # str() needed for mypy compatibility with SQLAlchemy comparison operators
        return session.execute(
            select(cls).where(cls.snapshot_slug == str(snapshot_slug), cls.fp_id == fp_id)
        ).scalar_one_or_none()

    @classmethod
    def get_for_snapshot(cls, snapshot_slug: SnapshotSlug) -> list[FalsePositive]:
        """Get all false positives for a snapshot."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        # str() needed for mypy compatibility with SQLAlchemy comparison operators
        return list(session.execute(select(cls).where(cls.snapshot_slug == str(snapshot_slug))).scalars().all())


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
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False
    )
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
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False
    )
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
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False
    )
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


class RunCost(Base):
    """Cost metrics from run_costs database VIEW (not a table).

    Aggregates token usage and costs per transcript+model from the Event table.
    Used by prompt optimizer queries to track evaluation costs.

    The view is automatically created via DDL event listener during metadata.create_all().
    """

    __tablename__ = "run_costs"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012

    # Tell SQLAlchemy NOT to create this as a table
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    transcript_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    model: Mapped[str] = mapped_column(String, primary_key=True)
    cost_usd: Mapped[float] = mapped_column(nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False)
    cached_tokens: Mapped[int] = mapped_column(nullable=False)
    output_tokens: Mapped[int] = mapped_column(nullable=False)


# ============================================================================
# DDL Event Listeners for Views
# ============================================================================


@event.listens_for(Base.metadata, "after_create")
def create_run_costs_view(target, connection, **kw):
    """Automatically create run_costs view after tables are created.

    This is idiomatic SQLAlchemy - the view creation is declarative and
    happens automatically during metadata.create_all().
    """
    # Drop existing table/view for one-time migration (old databases had it as a table)
    connection.execute(DDL("DROP TABLE IF EXISTS run_costs CASCADE"))
    connection.execute(DDL("DROP VIEW IF EXISTS run_costs CASCADE"))

    # Build view query programmatically using SQLAlchemy
    input_tokens_raw = Event.payload["usage"]["input_tokens"].astext
    cached_tokens_raw = Event.payload["usage"]["input_tokens_details"]["cached_tokens"].astext
    output_tokens_raw = Event.payload["usage"]["output_tokens"].astext
    reasoning_tokens_raw = Event.payload["usage"]["output_tokens_details"]["reasoning_tokens"].astext

    input_tokens_int = cast(input_tokens_raw, Integer)
    cached_tokens_int = func.coalesce(cast(cached_tokens_raw, Integer), 0)
    output_tokens_int = cast(output_tokens_raw, Integer)

    uncached_tokens = input_tokens_int - cached_tokens_int
    cost_usd = (
        uncached_tokens * ModelPricing.input_usd_per_1m_tokens / 1000000.0
        + cached_tokens_int * ModelPricing.cached_input_usd_per_1m_tokens / 1000000.0
        + output_tokens_int * ModelPricing.output_usd_per_1m_tokens / 1000000.0
    ).label("cost_usd")

    run_costs_query = (
        select(
            Event.payload["response_id"].astext.label("response_id"),
            Event.transcript_id,
            Event.payload["usage"]["model"].astext.label("model"),
            input_tokens_int.label("input_tokens"),
            cached_tokens_int.label("cached_tokens"),
            output_tokens_int.label("output_tokens"),
            func.coalesce(cast(reasoning_tokens_raw, Integer), 0).label("reasoning_tokens"),
            cost_usd,
            Event.timestamp,
        )
        .select_from(Event)
        .join(ModelPricing, Event.payload["usage"]["model"].astext == ModelPricing.model_id)
        .where(Event.event_type == "response", Event.payload["usage"] != None)  # noqa: E711
    )

    # Compile query to SQL
    compiled_query = run_costs_query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})

    # Create the view
    connection.execute(DDL(f"CREATE VIEW run_costs AS {compiled_query}"))
    connection.commit()
