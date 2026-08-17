"""SQLAlchemy schema for the Haku semantic index.

The semantic index has three layers:

- ``contents`` is the global, content-addressed collection of exact strings the document
  embedder sees.  ``content_sha`` always means the SHA-256 of ``content.encode("utf-8")``.
- ``content_embeddings`` is the vector produced when one such string is embedded by one model.
  It is durable index data, not an evictable cache: a model migration adds rows here while
  retaining the input content.
- corpus tables describe occurrences of that content.  Git chunk occurrences identify a span in
  a blob; chat windows identify a span in a conversation and the messages it covers.

Keeping those identities separate is what lets identical input text share a vector across Git
and conversations, across source revisions, and across chunker layouts.  The source rows still
hold the provenance a result needs to cite; only the content and its embedding are global.
"""

from __future__ import annotations

import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from haku.recall_index.vector_type import HalfVector

SCHEMA = "state_index"


class Corpus(StrEnum):
    """A source-specific occurrence table in the semantic index."""

    GIT = "git"
    CHAT = "chat"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Content(Base):
    """One exact normalized input string, globally content-addressed.

    The stored value is deliberately named ``content`` rather than ``text`` or ``plaintext``:
    it is the canonical content whose hash names it and whose bytes are sent to an embedder.
    """

    __tablename__ = "contents"

    content_sha: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContentEmbedding(Base):
    """One model's semantic representation of one globally-addressed content value."""

    __tablename__ = "content_embeddings"

    content_sha: Mapped[str] = mapped_column(Text, ForeignKey(f"{SCHEMA}.contents.content_sha"), primary_key=True)
    # The model key identifies the vector space.  It is part of the key because the same content
    # may be embedded by a replacement model or a distinct document-normalization regime.
    model_key: Mapped[str] = mapped_column(Text, primary_key=True)
    # Unconstrained ``halfvec``: the dimension belongs to ``model_key``.  See vector_type.py for
    # why the index uses half precision and why a dimension typmod would make model changes DDL.
    embedding: Mapped[list[float]] = mapped_column(HalfVector, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GitChunk(Base):
    """A chunk occurrence in one Git blob under one Git chunker regime."""

    __tablename__ = "git_chunks"

    blob_sha: Mapped[str] = mapped_column(Text, primary_key=True)
    chunker_key: Mapped[str] = mapped_column(Text, primary_key=True)
    byte_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    byte_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha: Mapped[str] = mapped_column(Text, ForeignKey(f"{SCHEMA}.contents.content_sha"), nullable=False)


class GitTipEntry(Base):
    """One path at the indexed commit. Replaced wholesale every sync."""

    __tablename__ = "git_tip"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    blob_sha: Mapped[str] = mapped_column(Text, nullable=False)


class GitSyncState(Base):
    """What the branch holds and what ``git_tip`` holds. One row; ``id`` is pinned to 1."""

    __tablename__ = "git_sync_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_git_sync_state_singleton"),
        CheckConstraint(
            "(commit_sha IS NULL) = (chunker_key IS NULL)"
            " AND (commit_sha IS NULL) = (model_key IS NULL)"
            " AND (commit_sha IS NULL) = (synced_at IS NULL)",
            name="ck_git_sync_state_indexed_half",
        ),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    branch: Mapped[str] = mapped_column(Text, nullable=False)
    remote_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_seen_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunker_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatChunk(Base):
    """One searchable window of a chat session, pointing to globally-addressed content."""

    __tablename__ = "chat_chunks"

    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    window_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_sha: Mapped[str] = mapped_column(Text, ForeignKey(f"{SCHEMA}.contents.content_sha"), nullable=False)
    first_message_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatChunkMessage(Base):
    """This chat window holds these messages, in order."""

    __tablename__ = "chat_chunk_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "window_no"],
            [f"{SCHEMA}.chat_chunks.session_id", f"{SCHEMA}.chat_chunks.window_no"],
            ondelete="CASCADE",
        ),
        Index("idx_chat_chunk_messages_message", "message_id"),
    )

    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    window_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class ChatSessionState(Base):
    """The source shape and retrieval regime at which one session was last indexed."""

    __tablename__ = "chat_sessions"

    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_message_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chunker_key: Mapped[str] = mapped_column(Text, nullable=False)
    model_key: Mapped[str] = mapped_column(Text, nullable=False)
    indexed_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
