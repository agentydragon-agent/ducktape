"""SQLAlchemy models for properties evaluation results.

Database schema documentation:
- Setup and architecture: db/README.md
- Access patterns and RLS: AGENTS.md (Database section)
- Migrations: db/migrations/
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, TypeAdapter

if TYPE_CHECKING:
    from adgn.props.db.clustering_models import UnknownAssignment, UnknownCluster
    from adgn.props.db.examples import Example

from sqlalchemy import (
    Enum,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.schema import DDL
from sqlalchemy.types import TypeDecorator

from adgn.agent.events import EventType
from adgn.props.agent_types import (
    ClusteringTypeConfig,
    CriticTypeConfig,
    FreeformTypeConfig,
    GraderTypeConfig,
    ImprovementTypeConfig,
    PromptOptimizerTypeConfig,
    TypeConfig,
)
from adgn.props.db.snapshots import DBKnownFalsePositive, DBLocationAnchor, DBTruePositiveIssue
from adgn.props.ids import SnapshotSlug, _SnapshotSlugBase
from adgn.props.models.critic_scopes import ScopeKind
from adgn.props.models.snapshot import BundleFilter, Source
from adgn.props.models.true_positive import FalsePositiveOccurrence, TruePositiveOccurrence
from adgn.props.splits import Split

T = TypeVar("T", bound=BaseModel)


class AgentRunStatus(StrEnum):
    """Agent run status enumeration.

    Unified status for all agent types (critic, grader, prompt_optimizer, etc.).
    """

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
    REPORTED_FAILURE = "reported_failure"


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
        # warnings=False suppresses harmless union variant checking warnings
        return self._adapter.dump_python(value, mode="json", by_alias=True, warnings=False)  # type: ignore[no-any-return]

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


E = TypeVar("E", bound=StrEnum)


class StrEnumColumn(TypeDecorator[E]):
    """Generic SQLAlchemy column type for StrEnum types.

    Uses PostgreSQL ENUM type with values derived from the Python enum.
    Automatically handles conversion between Python enum and database string.

    Usage:
        class MyEnum(StrEnum):
            FOO = "foo"
            BAR = "bar"

        # In type_annotation_map:
        MyEnum: StrEnumColumn(MyEnum, name="my_enum_type")

        # In model:
        my_field: Mapped[MyEnum] = mapped_column()
    """

    impl = Enum
    cache_ok = True

    def __init__(self, enum_class: type[E], name: str):
        """Initialize StrEnumColumn.

        Args:
            enum_class: The StrEnum class to use
            name: Name for the PostgreSQL enum type
        """
        self._enum_class = enum_class
        # Derive SQL enum values from Python enum to keep them in sync
        super().__init__(*[e.value for e in enum_class], name=name, create_constraint=True, native_enum=True)

    def process_bind_param(self, value: E | str | None, dialect: Any) -> str | None:
        """Convert enum to string for storage (Python → DB)."""
        if value is None:
            return None
        return value.value if isinstance(value, self._enum_class) else str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> E | None:
        """Convert string to enum after loading (DB → Python)."""
        if value is None:
            return None
        return self._enum_class(value)


class CanonicalIssuesSnapshot(BaseModel):
    """Snapshot of canonical true positives and false positives at grading time.

    Persisted in GraderRun.canonical_issues_snapshot to track which issues
    were used when grading a critique. This enables detecting stale grader runs
    after editing issue files.

    The serialized form is stored as JSONB in the database via PydanticColumn.

    Uses database-specific models (DBTruePositiveIssue, DBKnownFalsePositive)
    to decouple database persistence from MCP I/O protocol changes.
    """

    true_positives: list[DBTruePositiveIssue]
    false_positives: list[DBKnownFalsePositive]


class Base(DeclarativeBase):
    """Base class for all models."""

    type_annotation_map: ClassVar[dict[type, Any]] = {
        dict[str, Any]: JSONB,
        UUID: PG_UUID(as_uuid=True),
        SnapshotSlug: SnapshotSlugColumn(),
        Split: StrEnumColumn(Split, name="split_enum"),
        AgentRunStatus: StrEnumColumn(AgentRunStatus, name="agent_run_status_enum"),
    }


class Snapshot(Base):
    """Code snapshot with split assignment.

    Source of truth for snapshot→split mapping.
    Issues/false_positives reference snapshots by slug.
    """

    __tablename__ = "snapshots"

    slug: Mapped[SnapshotSlug] = mapped_column(SnapshotSlugColumn(), primary_key=True)
    split: Mapped[Split] = mapped_column(nullable=False)
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
    # CRITICAL: order_by ensures deterministic ordering for GEPA checkpoint compatibility
    # GEPA maps Example → DataId via list position, so examples must load in stable order
    examples: Mapped[list[Example]] = relationship(
        "Example",
        foreign_keys="[Example.snapshot_slug]",
        back_populates="snapshot_obj",
        cascade="all, delete-orphan",
        order_by="Example.scope_hash",
    )

    @classmethod
    def get(cls, slug: SnapshotSlug) -> Snapshot | None:
        """Get snapshot by slug."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return session.execute(select(cls).where(cls.slug == slug)).scalar_one_or_none()  # type: ignore[arg-type]

    @classmethod
    def get_by_split(cls, split: str) -> list[Snapshot]:
        """Get all snapshots for a split (train/valid/test)."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(session.execute(select(cls).where(cls.split == split)).scalars().all())

    def files_with_issues(self) -> set[Path]:
        """Return files with ground truth TP or FP issues."""
        tp_files = {
            file_path for tp in self.true_positives for occurrence in tp.occurrences for file_path in occurrence.files
        }
        fp_files = {
            file_path for fp in self.false_positives for occurrence in fp.occurrences for file_path in occurrence.files
        }
        return tp_files | fp_files


class TruePositive(Base):
    """True positive (expected findings).

    Composite primary key: (snapshot_slug, tp_id).
    Each true positive has one or more occurrences with expect_caught_from semantics.
    """

    __tablename__ = "true_positives"

    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        SnapshotSlugColumn(), ForeignKey("snapshots.slug", ondelete="RESTRICT"), primary_key=True
    )
    tp_id: Mapped[str] = mapped_column(String, primary_key=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[list[TruePositiveOccurrence]] = mapped_column(
        PydanticColumn(list[TruePositiveOccurrence]), nullable=False
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
        return session.execute(
            select(cls).where(cls.snapshot_slug == snapshot_slug, cls.tp_id == tp_id)  # type: ignore[arg-type]
        ).scalar_one_or_none()

    @classmethod
    def get_for_snapshot(cls, snapshot_slug: SnapshotSlug) -> list[TruePositive]:
        """Get all true positives for a snapshot."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(session.execute(select(cls).where(cls.snapshot_slug == snapshot_slug)).scalars().all())  # type: ignore[arg-type]


class FalsePositive(Base):
    """Known false positive (issue that looks like a problem but isn't).

    Composite primary key: (snapshot_slug, fp_id).
    Each FP has one or more occurrences with relevant_files semantics.
    """

    __tablename__ = "false_positives"

    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        SnapshotSlugColumn(), ForeignKey("snapshots.slug", ondelete="RESTRICT"), primary_key=True
    )
    fp_id: Mapped[str] = mapped_column(String, primary_key=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[list[FalsePositiveOccurrence]] = mapped_column(
        PydanticColumn(list[FalsePositiveOccurrence]), nullable=False
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
        return session.execute(
            select(cls).where(cls.snapshot_slug == snapshot_slug, cls.fp_id == fp_id)  # type: ignore[arg-type]
        ).scalar_one_or_none()

    @classmethod
    def get_for_snapshot(cls, snapshot_slug: SnapshotSlug) -> list[FalsePositive]:
        """Get all false positives for a snapshot."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(session.execute(select(cls).where(cls.snapshot_slug == snapshot_slug)).scalars().all())  # type: ignore[arg-type]


class ReportedIssue(Base):
    """Issue reported by an agent during code review.

    Part of the critic workflow - agent creates issue headers and links occurrences.
    Uses compound primary key (agent_run_id, issue_id) for scoped uniqueness.
    Agent uses hard DELETE to remove incorrect issues.
    """

    __tablename__ = "reported_issues"

    agent_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.agent_run_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        server_default=FetchedValue(),
    )
    issue_id: Mapped[str] = mapped_column(String, primary_key=True, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    # Relationships
    agent_run: Mapped[AgentRun] = relationship(back_populates="reported_issues")
    occurrences: Mapped[list[ReportedIssueOccurrence]] = relationship(
        back_populates="reported_issue", cascade="all, delete-orphan"
    )


class ReportedIssueOccurrence(Base):
    """Specific location(s) for a reported issue.

    Each occurrence has 1+ locations (JSONB array).
    Each location: {file: str, start_line?: int, end_line?: int}

    Example:
    locations = [
        {"file": "src/foo.py", "start_line": 10, "end_line": 20},
        {"file": "src/bar.py", "start_line": 30, "end_line": 40}
    ]

    CHECK constraint ensures locations is non-empty array.
    """

    __tablename__ = "reported_issue_occurrences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, server_default=FetchedValue())
    reported_issue_id: Mapped[str] = mapped_column(String, nullable=False)

    # Locations array (1+ location anchors)
    # Each location: DBLocationAnchor(file: str, start_line?: int, end_line?: int)
    locations: Mapped[list[DBLocationAnchor]] = mapped_column(PydanticColumn(list[DBLocationAnchor]), nullable=False)

    # Audit trail
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Foreign key to composite primary key
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_run_id", "reported_issue_id"],
            ["reported_issues.agent_run_id", "reported_issues.issue_id"],
            ondelete="CASCADE",
        ),
    )

    # Relationships
    reported_issue: Mapped[ReportedIssue] = relationship(back_populates="occurrences")


class GradingDecision(Base):
    """Grading decision linking an input issue to a ground truth occurrence (or no-match).

    Unified table for TP, FP, and no-match decisions (discriminated by NULL pattern):
    - TP match: target_tp_id + target_tp_occurrence_id are NOT NULL
    - FP match: target_fp_id + target_fp_occurrence_id are NOT NULL
    - No match: All targets are NULL, credit must be 0.0

    Database constraints:
    - CHECK constraint ensures input_issue_id corresponds to a reported issue in the
      critique being graded (validates via agent_run -> reported_issues)
    - SQL trigger enforces credit sum ≤1.0 per occurrence (see check_credit_sum function)

    Agent uses hard DELETE to remove incorrect decisions.
    """

    __tablename__ = "grading_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.agent_run_id", ondelete="CASCADE"),
        nullable=False,
        server_default=FetchedValue(),
    )
    input_issue_id: Mapped[str] = mapped_column(String, nullable=False)

    # Target: TP occurrence (nullable)
    target_tp_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_tp_occurrence_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Target: FP occurrence (nullable)
    target_fp_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_fp_occurrence_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Matching metadata
    credit: Mapped[float] = mapped_column(nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # Audit trail
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    # Relationships
    agent_run: Mapped[AgentRun] = relationship(back_populates="grading_decisions")

    @classmethod
    def get_active_for_run(cls, session: Session, agent_run_id: UUID) -> list[GradingDecision]:
        """Get all decisions for a grader agent run.

        Note: Soft-delete was removed, so all persisted decisions are active.
        """
        return list(
            session.execute(select(cls).where(cls.agent_run_id == agent_run_id).order_by(cls.created_at))
            .scalars()
            .all()
        )


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

    Linked to agent runs via agent_run_id foreign key.

    The payload column automatically serializes/deserializes EventType via EventTypeColumn.
    Access event.payload to get a typed EventType instance, set it to store.
    """

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence_num", name="uq_events_agent_run_id_seq"),
        Index("ix_events_agent_run_id_seq", "agent_run_id", "sequence_num"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_runs.agent_run_id", ondelete="CASCADE"), nullable=False
    )
    sequence_num: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    payload: Mapped[EventType] = mapped_column(PydanticColumn(EventType), nullable=False)  # type: ignore[arg-type]
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    agent_run: Mapped[AgentRun] = relationship(back_populates="events")


class RunCost(Base):
    """Cost metrics from run_costs database VIEW (not a table).

    Aggregates token usage and costs per agent_run+model from the Event table.
    Used by prompt optimizer queries to track evaluation costs.

    The view is automatically created via DDL event listener during metadata.create_all().
    """

    __tablename__ = "run_costs"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012

    # Tell SQLAlchemy NOT to create this as a table
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    agent_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    model: Mapped[str] = mapped_column(String, primary_key=True)
    cost_usd: Mapped[float] = mapped_column(nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False)
    cached_tokens: Mapped[int] = mapped_column(nullable=False)
    output_tokens: Mapped[int] = mapped_column(nullable=False)


class OccurrenceCredit(Base):
    """Occurrence credits from occurrence_credits database VIEW (not a table).

    Detailed view with one row per (grader_run, occurrence), fully denormalized for filtering/grouping:
    - Run identification (grader_run_id, graded_at)
    - Snapshot/Example context (snapshot_slug, split, scope_hash, scope_kind, reviewed_scope)
    - Critique provenance (critic_run_id, agent_definition_id)
    - Models (critic_model, grader_model)
    - Occurrence details (tp_id, occurrence_id, found_credit, matched_by_json, grader_rationale)

    The view is created by migration 20251226000002_recreate_views_for_agent_runs.py.
    """

    __tablename__ = "occurrence_credits"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Composite primary key (grader_run_id, tp_id, occurrence_id)
    grader_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tp_id: Mapped[str] = mapped_column(String, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(String, primary_key=True)

    # Run identification
    graded_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)

    # Snapshot/Example context
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(SnapshotSlugColumn(), nullable=False)
    split: Mapped[Split] = mapped_column(nullable=False)
    scope_hash: Mapped[str] = mapped_column(String, nullable=False)
    scope_kind: Mapped[ScopeKind] = mapped_column(String, nullable=False)
    reviewed_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Critique provenance
    critic_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    agent_definition_id: Mapped[str] = mapped_column(String, nullable=False)

    # Models
    critic_model: Mapped[str] = mapped_column(String, nullable=False)
    grader_model: Mapped[str | None] = mapped_column(String, nullable=True)

    # Occurrence details
    found_credit: Mapped[float] = mapped_column(nullable=False)
    matched_by_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    grader_rationale: Mapped[str] = mapped_column(Text, nullable=False)


class CriticRunOccurrenceStats(Base):
    """Per-critic-run occurrence statistics from critic_run_occurrence_stats database VIEW.

    Intermediate view that aggregates occurrence metrics per critic run, across all graders:
    - avg_occurrences_caught: Average raw occurrence count across graders for this run
    - n_catchable_occurrences: Total occurrences that could be caught (computed once)
    - n_grader_runs: How many graders ran on this critic run

    This eliminates duplication - both aggregated_recall_by_definition and
    aggregated_recall_by_example SELECT from this view.

    Failed critic runs (max_turns/context_length) have avg_occurrences_caught = NULL.

    The view was originally created by migration 20251217000001_aggregate_over_graders.py
    and updated to use agent_definition_id by migration 20251226000002_recreate_views_for_agent_runs.py
    """

    __tablename__ = "critic_run_occurrence_stats"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Primary key
    critic_run_id: Mapped[UUID] = mapped_column(primary_key=True)

    # Identifiers
    agent_definition_id: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(SnapshotSlugColumn(), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String, nullable=False)
    scope_kind: Mapped[str] = mapped_column(String, nullable=False)
    split: Mapped[Split] = mapped_column(nullable=False)
    critic_model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(nullable=False)

    # Occurrence metrics (aggregated across graders)
    avg_occurrences_caught: Mapped[float | None] = mapped_column(nullable=True)
    n_catchable_occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    n_grader_runs: Mapped[int] = mapped_column(Integer, nullable=False)


class AggregatedRecallByDefinition(Base):
    """Aggregated recall by agent definition from aggregated_recall_by_definition database VIEW.

    Computes occurrence-based weighted metrics per (split, agent_definition_id, critic_model, scope_kind):
    - Aggregates over all grader models (grader_model removed from GROUP BY)
    - Grouped by scope_kind to allow filtering by scope type (entire_snapshot vs explicit_files)
    - Computes raw occurrence counts (not percentages) for occurrence-based weighting
    - Tracks catchable occurrences for dataset-level recall computation
    - Splits metrics: among_successful vs overall (includes failures as zero)
    - Explicit failure tracking (max_turns_exceeded, context_length_exceeded, reported_failure)

    OCCURRENCE-BASED WEIGHTING:
    Examples with more occurrences contribute proportionally more to aggregate metrics.
    Dataset-level recall: SUM(avg_occurrences_caught) / SUM(total_catchable_occurrences)
    This is NOT average of per-example percentages.

    Use cases:
    - CLI stats: "Show me occurrence-weighted recall for all definitions on VALID split"
    - Prompt optimizer: "Which definition catches the most occurrences on TRAIN?"
    - Scope-specific analysis: "How do definitions perform on full-snapshot vs per-file examples?"
    - Leaderboard queries
    - Failure analysis: "Which definitions frequently hit max_turns or context limits?"

    The view is created by migration 20251226000002_recreate_views_for_agent_runs.py
    """

    __tablename__ = "aggregated_recall_by_definition"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Composite primary key (matches view GROUP BY - no grader_model!)
    split: Mapped[Split] = mapped_column(primary_key=True)
    agent_definition_id: Mapped[str] = mapped_column(String, primary_key=True)
    critic_model: Mapped[str] = mapped_column(String, primary_key=True)
    scope_kind: Mapped[str] = mapped_column(String, primary_key=True)

    # Count by outcome
    n_successful: Mapped[int] = mapped_column(Integer, nullable=False)
    n_max_turns_exceeded: Mapped[int] = mapped_column(Integer, nullable=False)
    n_context_length_exceeded: Mapped[int] = mapped_column(Integer, nullable=False)
    n_reported_failure: Mapped[int] = mapped_column(Integer, nullable=False)

    # Total examples and runs (added in 20251220000003)
    n_examples: Mapped[int] = mapped_column(Integer, nullable=False)
    n_runs: Mapped[int] = mapped_column(Integer, nullable=False)

    # Occurrence counts (raw counts, not percentages!)
    avg_occurrences_caught_among_successful: Mapped[float | None] = mapped_column(nullable=True)
    occurrences_variance_among_successful: Mapped[float | None] = mapped_column(nullable=True)
    avg_occurrences_caught_overall: Mapped[float] = mapped_column(nullable=False)

    # Catchable occurrences (for dataset-level recall)
    avg_catchable_occurrences: Mapped[float] = mapped_column(nullable=False)
    total_catchable_occurrences: Mapped[int] = mapped_column(Integer, nullable=False)

    # Computed recall and confidence bounds (added in 20251220000003)
    recall: Mapped[float | None] = mapped_column(nullable=True)
    ucb: Mapped[float | None] = mapped_column(nullable=True)
    lcb: Mapped[float | None] = mapped_column(nullable=True)

    # Grader metadata
    avg_grader_runs_per_critic: Mapped[float] = mapped_column(nullable=False)
    total_grader_runs: Mapped[int] = mapped_column(Integer, nullable=False)


class AggregatedRecallByExample(Base):
    """Aggregated recall by example from aggregated_recall_by_example database VIEW (not a table).

    Computes occurrence-based weighted metrics per (split, snapshot_slug, scope_hash, critic_model):
    - Aggregates over all grader models (grader_model removed from GROUP BY)
    - Same semantics as aggregated_recall_by_definition but grouped by example instead of definition
    - Computes raw occurrence counts (not percentages) for occurrence-based weighting
    - Tracks catchable occurrences for dataset-level recall computation

    Use cases:
    - CLI stats: "Show me per-example breakdown with occurrence weighting"
    - Prompt improver: "Which examples does this prompt struggle with?"
    - Training data analysis

    The view is created and updated by migration 20251217000001_aggregate_over_graders.py
    """

    __tablename__ = "aggregated_recall_by_example"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Composite primary key (no grader_model!)
    split: Mapped[Split] = mapped_column(primary_key=True)
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(SnapshotSlugColumn(), primary_key=True)
    scope_hash: Mapped[str] = mapped_column(String, primary_key=True)
    critic_model: Mapped[str] = mapped_column(String, primary_key=True)

    # Count by outcome
    n_successful: Mapped[int] = mapped_column(Integer, nullable=False)
    n_max_turns_exceeded: Mapped[int] = mapped_column(Integer, nullable=False)
    n_context_length_exceeded: Mapped[int] = mapped_column(Integer, nullable=False)
    n_reported_failure: Mapped[int] = mapped_column(Integer, nullable=False)

    # Total runs for this (example, critic_model) combination (added in 20251220000003)
    n_runs: Mapped[int] = mapped_column(Integer, nullable=False)

    # Occurrence counts (raw counts, not percentages!)
    avg_occurrences_caught_among_successful: Mapped[float | None] = mapped_column(nullable=True)
    occurrences_variance_among_successful: Mapped[float | None] = mapped_column(nullable=True)
    avg_occurrences_caught_overall: Mapped[float] = mapped_column(nullable=False)

    # Catchable occurrences (for dataset-level recall)
    avg_catchable_occurrences: Mapped[float] = mapped_column(nullable=False)
    total_catchable_occurrences: Mapped[int] = mapped_column(Integer, nullable=False)

    # Computed recall (added in 20251220000003)
    recall: Mapped[float | None] = mapped_column(nullable=True)

    # Grader metadata
    avg_grader_runs_per_critic: Mapped[float] = mapped_column(nullable=False)
    total_grader_runs: Mapped[int] = mapped_column(Integer, nullable=False)


class ParetoFrontierByExample(Base):
    """Pareto frontier from pareto_frontier_by_example database VIEW (not a table).

    For each example, shows the best recall achieved and which agent definitions achieved it.
    Useful for prompt optimization to identify:
    - Which definitions excel on specific examples (definition specialization)
    - Examples where no definition performs well (improvement opportunities)
    - Generalist vs specialist definition patterns

    Use cases:
    - Prompt optimizer: "Which agent definitions win on which examples?"
    - Ensemble analysis: Combine best definitions for different patterns
    - Training diagnostics: "Where do all definitions struggle?"

    The view is created by Alembic migration 20251226000002_recreate_views_for_agent_runs.py.
    """

    __tablename__ = "pareto_frontier_by_example"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Composite primary key
    split: Mapped[Split] = mapped_column(primary_key=True)
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(SnapshotSlugColumn(), primary_key=True)
    scope_hash: Mapped[str] = mapped_column(String, primary_key=True)
    scope_kind: Mapped[str] = mapped_column(String, primary_key=True)
    critic_model: Mapped[str] = mapped_column(String, primary_key=True)

    # Pareto frontier data
    best_recall: Mapped[float] = mapped_column(nullable=False)
    winning_definition_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    winning_definition_n_runs: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)


class OccurrenceStatistics(Base):
    """Occurrence statistics from occurrence_statistics database VIEW (not a table).

    Statistics per (split, tp_id, occurrence_id, critic_model, grader_model) across all runs:
    - Mean, stddev, min, max credit
    - Number of runs and prompts
    - Full catch rate (how often credit = 1.0)

    Use cases:
    - Identify "hard" occurrences (low mean_credit, high variance)
    - Training diagnostics: "Which occurrences are never caught?"
    - Prompt improver: "Focus on occurrences with low full_catch_rate"

    The view is created by Alembic migration 20251215000002_add_occurrence_views.py.
    """

    __tablename__ = "occurrence_statistics"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Composite primary key
    split: Mapped[Split] = mapped_column(primary_key=True)
    tp_id: Mapped[str] = mapped_column(String, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(String, primary_key=True)
    critic_model: Mapped[str] = mapped_column(String, primary_key=True)
    grader_model: Mapped[str] = mapped_column(String, primary_key=True)

    # Statistics
    mean_credit: Mapped[float] = mapped_column(nullable=False)
    stddev_credit: Mapped[float | None] = mapped_column(nullable=True)  # NULL for single run
    min_credit: Mapped[float] = mapped_column(nullable=False)
    max_credit: Mapped[float] = mapped_column(nullable=False)
    n_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    n_prompts: Mapped[int] = mapped_column(Integer, nullable=False)
    full_catch_rate: Mapped[float] = mapped_column(nullable=False)


# ============================================================================
# Agent Definition Tables
# ============================================================================


class AgentDefinition(Base):
    """Agent definition archive stored in database.

    Contains AGENT.md, init script, tools, examples, and docs packed as tar.
    Definitions can be repo-backed (readable names) or agent-created (auto-generated IDs).
    """

    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_type: Mapped[str] = mapped_column(String, nullable=False)  # agent_type_enum value
    archive: Mapped[bytes] = mapped_column(postgresql.BYTEA, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    created_by_agent_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)

    # Relationships
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="agent_definition")


class AgentRun(Base):
    """Unified agent run record (replaces separate critic_runs, grader_runs, etc.).

    Each run references an agent definition and stores type-specific config as JSONB.
    Parent-child relationships track sub-agent spawning.

    Status tracking:
    - status: Current run status (in_progress, completed, etc.)
    - completion_summary: Markdown summary from agent (when status='completed')
      or error message (when status='reported_failure')
    """

    __tablename__ = "agent_runs"

    agent_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_definition_id: Mapped[str] = mapped_column(String, ForeignKey("agent_definitions.id"), nullable=False)
    parent_agent_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_runs.agent_run_id"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    type_config: Mapped[TypeConfig] = mapped_column(PydanticColumn(TypeConfig), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        nullable=False,
        server_default="in_progress",
        comment="Run status: in_progress, completed, max_turns_exceeded, context_length_exceeded, or reported_failure",
    )
    completion_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Markdown summary from agent when status='completed', or error message when status='reported_failure'",
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    agent_definition: Mapped[AgentDefinition] = relationship(back_populates="agent_runs")
    parent: Mapped[AgentRun | None] = relationship("AgentRun", remote_side=[agent_run_id], backref="children")
    reported_issues: Mapped[list[ReportedIssue]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan"
    )
    grading_decisions: Mapped[list[GradingDecision]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan"
    )
    events: Mapped[list[Event]] = relationship(back_populates="agent_run", cascade="all, delete-orphan")
    unknown_clusters: Mapped[list[UnknownCluster]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan"
    )
    unknown_assignments: Mapped[list[UnknownAssignment]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan", foreign_keys="[UnknownAssignment.agent_run_id]"
    )

    # Type-safe config accessors
    def critic_config(self) -> CriticTypeConfig:
        """Get type_config as CriticTypeConfig or raise ValueError.

        Use when this run is expected to be a critic run.
        Raises ValueError if type_config is not CriticTypeConfig.
        """
        if isinstance(self.type_config, CriticTypeConfig):
            return self.type_config
        raise ValueError(f"Expected CriticTypeConfig, got {type(self.type_config).__name__}")

    def grader_config(self) -> GraderTypeConfig:
        """Get type_config as GraderTypeConfig or raise ValueError.

        Use when this run is expected to be a grader run.
        Raises ValueError if type_config is not GraderTypeConfig.
        """
        if isinstance(self.type_config, GraderTypeConfig):
            return self.type_config
        raise ValueError(f"Expected GraderTypeConfig, got {type(self.type_config).__name__}")

    def clustering_config(self) -> ClusteringTypeConfig:
        """Get type_config as ClusteringTypeConfig or raise ValueError.

        Use when this run is expected to be a clustering run.
        Raises ValueError if type_config is not ClusteringTypeConfig.
        """
        if isinstance(self.type_config, ClusteringTypeConfig):
            return self.type_config
        raise ValueError(f"Expected ClusteringTypeConfig, got {type(self.type_config).__name__}")

    def improvement_config(self) -> ImprovementTypeConfig:
        """Get type_config as ImprovementTypeConfig or raise ValueError.

        Use when this run is expected to be an improvement run.
        Raises ValueError if type_config is not ImprovementTypeConfig.
        """
        if isinstance(self.type_config, ImprovementTypeConfig):
            return self.type_config
        raise ValueError(f"Expected ImprovementTypeConfig, got {type(self.type_config).__name__}")

    def prompt_optimizer_config(self) -> PromptOptimizerTypeConfig:
        """Get type_config as PromptOptimizerTypeConfig or raise ValueError.

        Use when this run is expected to be a prompt optimizer run.
        Raises ValueError if type_config is not PromptOptimizerTypeConfig.
        """
        if isinstance(self.type_config, PromptOptimizerTypeConfig):
            return self.type_config
        raise ValueError(f"Expected PromptOptimizerTypeConfig, got {type(self.type_config).__name__}")

    def freeform_config(self) -> FreeformTypeConfig:
        """Get type_config as FreeformTypeConfig or raise ValueError.

        Use when this run is expected to be a freeform sub-agent run.
        Raises ValueError if type_config is not FreeformTypeConfig.
        """
        if isinstance(self.type_config, FreeformTypeConfig):
            return self.type_config
        raise ValueError(f"Expected FreeformTypeConfig, got {type(self.type_config).__name__}")


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
        uncached_tokens * ModelMetadata.input_usd_per_1m_tokens / 1000000.0
        + cached_tokens_int * ModelMetadata.cached_input_usd_per_1m_tokens / 1000000.0
        + output_tokens_int * ModelMetadata.output_usd_per_1m_tokens / 1000000.0
    ).label("cost_usd")

    run_costs_query = (
        select(
            Event.payload["response_id"].astext.label("response_id"),
            Event.agent_run_id,
            Event.payload["usage"]["model"].astext.label("model"),
            input_tokens_int.label("input_tokens"),
            cached_tokens_int.label("cached_tokens"),
            output_tokens_int.label("output_tokens"),
            func.coalesce(cast(reasoning_tokens_raw, Integer), 0).label("reasoning_tokens"),
            cost_usd,
            Event.timestamp,
        )
        .select_from(Event)
        .join(ModelMetadata, Event.payload["usage"]["model"].astext == ModelMetadata.model_id)
        .where(Event.event_type == "response", Event.payload["usage"] != None)  # noqa: E711
    )

    # Compile query to SQL
    compiled_query = run_costs_query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})

    # Create the view
    connection.execute(DDL(f"CREATE VIEW run_costs AS {compiled_query}"))
    connection.commit()


# Import clustering_models at end of module to register UnknownCluster/UnknownAssignment
# with SQLAlchemy's class registry. AgentRun has relationships to these classes using
# string references ("UnknownCluster", "UnknownAssignment") which SQLAlchemy resolves
# lazily. This import ensures the classes are registered before any queries execute.
# This must be at module scope (not inside TYPE_CHECKING) so it runs at import time.
from adgn.props.db import clustering_models as _clustering_models  # noqa: F401, E402
