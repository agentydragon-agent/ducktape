"""SQLAlchemy models for properties evaluation results.

Database schema documentation:
- Setup and architecture: db/README.md
- Access patterns and RLS: AGENTS.md (Database section)
- Migrations: db/migrations/
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import (
    Boolean,
    Enum,
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
from adgn.props.db.snapshots import (
    DBCriticOutput,
    DBCriticSubmitPayload,
    DBGraderOutput,
    DBKnownFalsePositive,
    DBTruePositiveIssue,
)
from adgn.props.files_hash import hash_file_set
from adgn.props.ids import SnapshotSlug, _SnapshotSlugBase
from adgn.props.models.snapshot import BundleFilter, Source
from adgn.props.models.true_positive import FalsePositiveOccurrence, TruePositiveOccurrence
from adgn.props.splits import Split

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


class SplitColumn(TypeDecorator[Split]):
    """SQLAlchemy column type for Split enum.

    Uses PostgreSQL ENUM type with values derived from Split enum.
    """

    impl = Enum
    cache_ok = True

    def __init__(self):
        # Derive SQL enum values from Python enum to keep them in sync
        super().__init__(*[e.value for e in Split], name="split_enum", create_constraint=True, native_enum=True)

    def process_bind_param(self, value: Split | str | None, dialect: Any) -> str | None:
        """Convert Split enum to string for storage (Python → DB)."""
        if value is None:
            return None
        return value.value if isinstance(value, Split) else str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> Split | None:
        """Convert string to Split enum after loading (DB → Python)."""
        if value is None:
            return None
        return Split(value)


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
        Split: SplitColumn(),
    }


class Snapshot(Base):
    """Code snapshot with split assignment.

    Source of truth for snapshot→split mapping.
    Issues/false_positives reference snapshots by slug.
    """

    __tablename__ = "snapshots"

    slug: Mapped[SnapshotSlug] = mapped_column(SnapshotSlugColumn(), primary_key=True)
    split: Mapped[Split] = mapped_column(SplitColumn(), nullable=False)
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
    # GEPA maps SnapshotInput → DataId via list position, so examples must load in stable order
    examples: Mapped[list[Example]] = relationship(
        back_populates="snapshot_obj", cascade="all, delete-orphan", order_by="Example.files_hash"
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


class Example(Base):
    """Training/evaluation examples.

    Defines which file sets to evaluate against.
    All examples (train/valid/test) are stored here.

    Two kinds of examples:
    1. Whole-snapshot: is_whole_snapshot=TRUE, files=NULL, files_hash=NULL
       - One per snapshot (targets all files with issues)
    2. File-set: is_whole_snapshot=FALSE, files=JSONB list, files_hash=SHA256
       - Multiple per snapshot (targets specific file subsets)

    Auto-generated from expect_caught_from data at db sync time.
    See docs/training_strategy.md for details on example generation.
    """

    __tablename__ = "examples"
    __table_args__ = (
        Index("ix_examples_snapshot_slug", "snapshot_slug"),
        Index("uq_examples_whole_snapshot", "snapshot_slug", unique=True, postgresql_where="is_whole_snapshot = TRUE"),
        Index(
            "uq_examples_file_set",
            "snapshot_slug",
            "files_hash",
            unique=True,
            postgresql_where="is_whole_snapshot = FALSE",
        ),
    )

    # Primary key (surrogate)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        SnapshotSlugColumn(), ForeignKey("snapshots.slug", ondelete="CASCADE"), nullable=False
    )

    # Example type flag
    is_whole_snapshot: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=func.false(),
        comment="TRUE for whole-snapshot examples, FALSE for file-set examples",
    )

    # File-set fields (NULL for whole-snapshot examples)
    files_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="SHA256 hash of normalized files field (NULL for whole-snapshot)"
    )
    files: Mapped[list[str] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True, comment="List of file paths to review (NULL for whole-snapshot)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships (no back-populate from CriticRun - no FK)
    snapshot_obj: Mapped[Snapshot] = relationship(back_populates="examples")

    def __post_init__(self) -> None:
        """Validate Example invariants after construction."""
        self.validate()

    def validate(self) -> None:
        """Validate that this Example satisfies the check constraint.

        Raises:
            ValueError: If the example violates the constraint
        """
        if self.is_whole_snapshot:
            # Whole-snapshot example must have NULL files and files_hash
            if self.files is not None:
                raise ValueError("Whole-snapshot example must have files=None")
            if self.files_hash is not None:
                raise ValueError("Whole-snapshot example must have files_hash=None")
        else:
            # File-set example must have both files and files_hash
            if self.files is None:
                raise ValueError("File-set example must have files (not None)")
            if self.files_hash is None:
                raise ValueError("File-set example must have files_hash (not None)")
            # Validate files are sorted
            if self.files != sorted(self.files):
                raise ValueError(f"File-set example files must be sorted: {self.files}")

    @classmethod
    def whole_snapshot(cls, snapshot_slug: SnapshotSlug) -> Example:
        """Factory method for creating a whole-snapshot example.

        Args:
            snapshot_slug: The snapshot slug

        Returns:
            Example with is_whole_snapshot=TRUE, files=None, files_hash=None
        """
        return cls(snapshot_slug=snapshot_slug, is_whole_snapshot=True, files=None, files_hash=None)

    @classmethod
    def file_set(cls, snapshot_slug: SnapshotSlug, files: Iterable[str | Path]) -> Example:
        """Factory method for creating a file-set example.

        Encapsulates file normalization (sorting, stringification) and hash computation.

        Args:
            snapshot_slug: The snapshot slug
            files: File paths (any iterable of str or Path objects)

        Returns:
            Example with is_whole_snapshot=FALSE, populated files and files_hash
        """
        # Normalize to sorted list of strings
        files_list = sorted(str(p) for p in files)

        # Compute hash
        files_hash = hash_file_set(files_list)

        return cls(snapshot_slug=snapshot_slug, is_whole_snapshot=False, files=files_list, files_hash=files_hash)

    @classmethod
    def get_for_snapshot(cls, snapshot_slug: SnapshotSlug) -> list[Example]:
        """Get all examples for a snapshot."""

        session = Session.object_session(cls)
        if session is None:
            raise RuntimeError("Model not bound to session")
        return list(session.execute(select(cls).where(cls.snapshot_slug == snapshot_slug)).scalars().all())  # type: ignore[arg-type]


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

    Payload uses DBCriticSubmitPayload (DB persistence model).
    """

    __tablename__ = "critiques"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        SnapshotSlugColumn(), ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False
    )
    # TODO: Add critic_scope_id FK to critic_scopes table to track which scope was used
    # for targeted reviews (not full-snapshot). This enables per-scope evaluation metrics
    # and better attribution of critique results to specific training examples.
    payload: Mapped[DBCriticSubmitPayload] = mapped_column(
        PydanticColumn(DBCriticSubmitPayload),
        nullable=False,
        comment="Critique payload (DB model). Conversion to/from MCP model happens in critic layer.",
    )
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
        SnapshotSlugColumn(), ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    critique_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("critiques.id"), nullable=True)
    prompt_optimization_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("prompt_optimization_runs.id"), nullable=True, index=True
    )
    files: Mapped[list[str]] = mapped_column(JSONB, nullable=False, comment="Files in critic scope")
    files_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA256 hash of sorted file paths for cache lookup"
    )
    output: Mapped[DBCriticOutput | None] = mapped_column(
        PydanticColumn(DBCriticOutput),
        nullable=True,
        comment="Critic output (discriminated union: success, max_turns_exceeded, or context_length_exceeded). NULL only during initial creation, always set after run completes.",
    )
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

    Tracking canonical issues:
        canonical_issues_snapshot stores the TPs+FPs used at grading time.
        This enables detecting stale grader runs after editing issue files.

        To find stale runs for a snapshot:
            1. Load current canonical TPs+FPs from registry
            2. Serialize with TypeAdapter + canonicaljson (same as grader.py)
            3. Query for runs where canonical_issues_snapshot != current snapshot
    """

    __tablename__ = "grader_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(
        SnapshotSlugColumn(), ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    critique_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("critiques.id"), nullable=False)
    prompt_optimization_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("prompt_optimization_runs.id"), nullable=True, index=True
    )
    canonical_issues_snapshot: Mapped[CanonicalIssuesSnapshot] = mapped_column(
        PydanticColumn(CanonicalIssuesSnapshot),
        nullable=False,
        comment="Snapshot of canonical TPs+FPs used at grading time",
    )
    output: Mapped[DBGraderOutput] = mapped_column(
        PydanticColumn(DBGraderOutput),
        nullable=False,
        comment="Grader output (discriminated union: success or max_turns_exceeded)",
    )
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


class OccurrenceCredit(Base):
    """Occurrence credits from occurrence_credits database VIEW (not a table).

    Detailed view with one row per (grader_run, occurrence), fully denormalized for filtering/grouping:
    - Run identification (grader_run_id, transcript_id, graded_at)
    - Snapshot/Example context (snapshot_slug, split, files_hash, is_whole_snapshot, reviewed_files)
    - Critique provenance (critique_id, critic_run_id, critic_transcript_id, prompt_sha256, prompt_text)
    - Models (critic_model, grader_model)
    - Occurrence details (tp_id, occurrence_id, found_credit, matched_by_json, grader_rationale)

    The view is created by Alembic migration 20251215000002_add_occurrence_views.py.
    """

    __tablename__ = "occurrence_credits"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Composite primary key (grader_run_id, tp_id, occurrence_id)
    grader_run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tp_id: Mapped[str] = mapped_column(String, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(String, primary_key=True)

    # Run identification
    grader_transcript_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    graded_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)

    # Snapshot/Example context
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(SnapshotSlugColumn(), nullable=False)
    split: Mapped[Split] = mapped_column(SplitColumn(), nullable=False)
    files_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_whole_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_files: Mapped[list[str]] = mapped_column(PydanticColumn(list[str]), nullable=False)

    # Critique provenance
    critique_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    critic_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    critic_transcript_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_optimization_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Models
    critic_model: Mapped[str] = mapped_column(String, nullable=False)
    grader_model: Mapped[str] = mapped_column(String, nullable=False)

    # Occurrence details
    found_credit: Mapped[float] = mapped_column(nullable=False)
    matched_by_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    grader_rationale: Mapped[str] = mapped_column(Text, nullable=False)


class AggregatedRecallByPrompt(Base):
    """Aggregated recall by prompt from aggregated_recall_by_prompt database VIEW (not a table).

    Aggregates recall metrics per (split, prompt_sha256, critic_model, grader_model, is_whole_snapshot):
    - Averages occurrence credits across replicate runs
    - Computes total credit, recall, and counts (occurrences, snapshots, examples, runs)
    - Includes confidence bounds (ucb, lcb) and variance (recall_stddev) for uncertainty awareness
    - Tracks failure modes (max_turns_exceeded, context_length_exceeded)

    Use cases:
    - CLI stats: "Show me recall for all prompts on VALID split"
    - Prompt optimizer: "Which prompt has highest recall on TRAIN?" (check n_examples >= 5, use UCB/LCB)
    - Leaderboard queries
    - Failure analysis: "Which prompts frequently get stuck?"

    The view is created by Alembic migration 20251215000002_add_occurrence_views.py
    and updated by migrations:
    - 20251215000008_add_failure_counts_to_aggregated_views.py (failure tracking)
    - 20251217000000_add_targeted_validation_mode.py (stats columns: n_runs, recall_stddev, ucb, lcb)
    """

    __tablename__ = "aggregated_recall_by_prompt"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Composite primary key (matches view GROUP BY)
    split: Mapped[Split] = mapped_column(SplitColumn(), primary_key=True)
    prompt_sha256: Mapped[str] = mapped_column(String, primary_key=True)
    critic_model: Mapped[str] = mapped_column(String, primary_key=True)
    is_whole_snapshot: Mapped[bool] = mapped_column(Boolean, primary_key=True)

    # Aggregated metrics
    total_credit: Mapped[float] = mapped_column(nullable=False)
    n_occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    recall: Mapped[float] = mapped_column(nullable=False)
    n_snapshots: Mapped[int] = mapped_column(Integer, nullable=False)
    n_examples: Mapped[int] = mapped_column(Integer, nullable=False)

    # Stats columns (added in migration 20251217000000)
    n_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    recall_stddev: Mapped[float | None] = mapped_column(nullable=True)
    ucb: Mapped[float] = mapped_column(nullable=False)
    lcb: Mapped[float] = mapped_column(nullable=False)

    # Failure tracking (added in migration 20251215000008)
    n_max_turns_exceeded: Mapped[int] = mapped_column(Integer, nullable=False)
    n_context_length_exceeded: Mapped[int] = mapped_column(Integer, nullable=False)


class AggregatedRecallByExample(Base):
    """Aggregated recall by example from aggregated_recall_by_example database VIEW (not a table).

    Aggregates recall metrics per (split, snapshot_slug, files_hash, critic_model, grader_model):
    - Averages occurrence credits across replicate runs
    - Computes total credit, recall, and occurrence count

    Use cases:
    - CLI stats: "Show me per-example breakdown"
    - Prompt improver: "Which examples does this prompt struggle with?"
    - Training data analysis

    The view is created by Alembic migration 20251215000002_add_occurrence_views.py.
    """

    __tablename__ = "aggregated_recall_by_example"
    __table_args__ = {"info": {"is_view": True}, "extend_existing": True}  # noqa: RUF012
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012

    # Composite primary key
    split: Mapped[Split] = mapped_column(SplitColumn(), primary_key=True)
    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(SnapshotSlugColumn(), primary_key=True)
    files_hash: Mapped[str] = mapped_column(String, primary_key=True)
    critic_model: Mapped[str] = mapped_column(String, primary_key=True)
    grader_model: Mapped[str] = mapped_column(String, primary_key=True)

    # Aggregated metrics
    total_credit: Mapped[float] = mapped_column(nullable=False)
    n_occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    recall: Mapped[float] = mapped_column(nullable=False)


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
    split: Mapped[Split] = mapped_column(SplitColumn(), primary_key=True)
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
        .join(ModelMetadata, Event.payload["usage"]["model"].astext == ModelMetadata.model_id)
        .where(Event.event_type == "response", Event.payload["usage"] != None)  # noqa: E711
    )

    # Compile query to SQL
    compiled_query = run_costs_query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})

    # Create the view
    connection.execute(DDL(f"CREATE VIEW run_costs AS {compiled_query}"))
    connection.commit()
