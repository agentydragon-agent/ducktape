"""Service-owned rows; PostgreSQL is the queue, prefix allocator, and recovery authority."""

from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Inbox(Base):
    __tablename__ = "inbox"
    __table_args__ = (UniqueConstraint("owner_namespace", "owner_name", "destination_key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_namespace: Mapped[str]
    owner_name: Mapped[str]
    destination_key: Mapped[str]
    destination_ref: Mapped[dict[str, str]] = mapped_column(JSONB)
    session_id: Mapped[str]
    last_cursor: Mapped[int] = mapped_column(BigInteger)
    acknowledged: Mapped[int] = mapped_column(BigInteger)
    covered: Mapped[int] = mapped_column(BigInteger)
    expired_through: Mapped[int] = mapped_column(BigInteger)
    retired: Mapped[bool]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Earliest inbox work: source reconciliation or notice delivery. None means no timed work.
    next_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    claim: Mapped[UUID | None]
    claim_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivery_error: Mapped[str | None]
    stale_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(Base):
    __tablename__ = "subscription"
    __table_args__ = (
        UniqueConstraint("inbox_id", "idempotency_key"),
        CheckConstraint("creation ? 'source'", name="subscription_creation_source"),
        CheckConstraint(
            "error_kind IN ('rate_limited', 'unavailable', 'access_denied', 'source_changed', 'processing_error')",
            name="subscription_error_kind",
        ),
        CheckConstraint(
            "(error IS NULL AND error_kind IS NULL AND error_since IS NULL AND error_observed_at IS NULL) OR "
            "(error IS NOT NULL AND error_kind IS NOT NULL AND error_since IS NOT NULL AND error_observed_at IS NOT NULL)",
            name="subscription_error_state",
        ),
        CheckConstraint(
            "CASE creation #>> '{source,provider}' "
            "WHEN 'actions' THEN actions_after_sequence IS NOT NULL AND github_start_position IS NULL "
            "AND github_binding IS NULL "
            "WHEN 'github' THEN actions_after_sequence IS NULL AND github_start_position IS NOT NULL "
            "AND github_binding IS NOT NULL ELSE false END",
            name="subscription_source_state",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    inbox_id: Mapped[UUID] = mapped_column(ForeignKey("inbox.id", ondelete="CASCADE"))
    idempotency_key: Mapped[str]
    creation: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    creator: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    version: Mapped[int]
    actions_after_sequence: Mapped[int | None] = mapped_column(BigInteger)
    # Immutable lower bound for GitHub receipts eligible for this subscription.
    github_start_position: Mapped[int | None] = mapped_column(BigInteger)
    generation: Mapped[int] = mapped_column(BigInteger, default=0)
    github_binding: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    cancelled: Mapped[bool]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Next source reconciliation, not a runner delivery timestamp; None waits for a new event.
    next_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None]
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_kind: Mapped[str | None]
    error_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Entry(Base):
    __tablename__ = "entry"
    __table_args__ = (UniqueConstraint("inbox_id", "event"),)
    inbox_id: Mapped[UUID] = mapped_column(ForeignKey("inbox.id", ondelete="CASCADE"), primary_key=True)
    cursor: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    payload: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Match(Base):
    __tablename__ = "subscription_match"
    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("subscription.id", ondelete="CASCADE"), primary_key=True)
    cursor: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class Notice(Base):
    __tablename__ = "notice"
    inbox_id: Mapped[UUID] = mapped_column(ForeignKey("inbox.id", ondelete="CASCADE"), primary_key=True)
    command_id: Mapped[UUID]
    through_cursor: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str]
    attempted: Mapped[bool]
    admitted: Mapped[bool]
    confirmed: Mapped[bool]
    error: Mapped[str | None]
    runner_cursor: Mapped[int] = mapped_column(BigInteger)
    runner_entry: Mapped[bytes | None] = mapped_column(LargeBinary)


class GitHubDelivery(Base):
    __tablename__ = "github_delivery"
    __table_args__ = (
        UniqueConstraint("app_id", "delivery_id"),
        Index("ix_github_delivery_head", "app_id", "repository_id", "head_sha"),
        Index("ix_github_delivery_subjects", "subjects", postgresql_using="gin"),
    )
    position: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    app_id: Mapped[int] = mapped_column(BigInteger)
    delivery_id: Mapped[UUID]
    installation_id: Mapped[int] = mapped_column(BigInteger)
    repository_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    event: Mapped[str]
    # Indexed matching metadata extracted from the retained, validated payload.
    action: Mapped[str | None]
    head_sha: Mapped[str | None]
    subjects: Mapped[list[str]] = mapped_column(ARRAY(String))
    digest: Mapped[bytes] = mapped_column(LargeBinary)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
