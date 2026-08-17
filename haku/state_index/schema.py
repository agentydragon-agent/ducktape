"""SQLAlchemy schema for the haku index.

`lexical_chunks` holds canonical, content-addressed chunk text independently of a model. It is
the durable first result of ingesting source material: a later full-text reader can use it even
when the embedding service is unavailable. `chunks` is the model-specific vector cache layered
over it. Keeping those facts separate means a source synchronizer can enqueue embedding work and
finish without waiting for the remote embedding service.

Everything else is per-corpus, and each table says which corpus it belongs to:

- **git** — `git_tip` is the tree at the indexed commit, replaced wholesale each sync, and
  `git_sync_state` records what that commit was. Search joins `git_tip` to `chunks`, so **the
  join is the tip filter**: content no longer at the tip is unreachable by construction, not by
  a delete pass that could be missed.
- **chat** — `chat_chunks` is the searchable window set, `chat_chunk_messages` records which
  messages each window holds, and `chat_sessions` records the shape of each session as last
  indexed. Chat has no equivalent of the tip join: a session's rows are replaced when it grows,
  and a session that leaves the source is swept by the sync (`chat_sync.sync_chat`), so
  retraction there is a step someone has to keep running rather than a property of the query.

`Corpus` is in `chunks`' primary key, which is what keeps the two apart. Each corpus supplies
its own kind of content address and its own chunker, so `content_sha` and `chunker_key` are
only ever comparable within one corpus.
"""

from __future__ import annotations

import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
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

from haku.state_index.vector_type import HalfVector
from util.sqlalchemy_types import TextBackedStrEnumColumn

SCHEMA = "state_index"


class Corpus(StrEnum):
    """Which body of content a chunk was embedded from.

    Part of `chunks`' primary key rather than a convention about hash lengths or key prefixes:
    a git blob sha and a hash of a rendered message window are different namespaces, and a
    search or a cache lookup that forgets to say which one it means is a bug the key shape
    should catch.
    """

    GIT = "git"
    CHAT = "chat"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class LexicalChunk(Base):
    """One canonical span of source text, before any model has embedded it.

    The primary key is the old vector-cache key without ``model_key``. A byte-identical git blob
    or chat window therefore has exactly one lexical representation under a chunker regime,
    while it may later have many embeddings as models change. ``text`` belongs here rather than
    in the vector cache: lexical search and source ingestion must not depend on an embedding
    having succeeded.
    """

    __tablename__ = "lexical_chunks"

    corpus: Mapped[Corpus] = mapped_column(TextBackedStrEnumColumn(Corpus), primary_key=True)
    content_sha: Mapped[str] = mapped_column(Text, primary_key=True)
    chunker_key: Mapped[str] = mapped_column(Text, primary_key=True)
    byte_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    byte_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Chunk(Base):
    """One embedded span of one piece of content, under one (corpus, chunker, model) regime.

    The primary key carries `chunker_key` and `model_key` so changing the chunker or the
    embedding model misses the cache instead of silently serving vectors computed over
    different text or by a different model. `chunker_key` is scoped by `corpus` — the two
    corpora chunk different things by different rules, and their version numbers move
    independently.
    """

    __tablename__ = "chunks"

    corpus: Mapped[Corpus] = mapped_column(TextBackedStrEnumColumn(Corpus), primary_key=True)
    # What this corpus addresses content by: the git blob sha for `git`, the sha256 of the
    # rendered message window for `chat`. Only ever compared within one corpus.
    content_sha: Mapped[str] = mapped_column(Text, primary_key=True)
    chunker_key: Mapped[str] = mapped_column(Text, primary_key=True)
    model_key: Mapped[str] = mapped_column(Text, primary_key=True)
    # Byte offsets of this chunk within the content `content_sha` addresses. For `git` that
    # content is the blob, so the span locates the chunk inside a file a caller can read back.
    # For `chat` the addressed content is the chunk itself, so the span covers all of it.
    #
    # `byte_start` is in the key because it is what distinguishes one chunk of a blob from the
    # next; an ordinal beside it would be a second name for the same fact, and document order is
    # this one's to define.
    byte_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    byte_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Kept during the expand migration because deployed vector readers still select it. New
    # writers source the canonical value from ``lexical_chunks``; a later contract migration can
    # remove this duplicate once every reader has crossed over.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Unconstrained `halfvec`: dimension is a property of `model_key`, and pinning a typmod here
    # would force a migration to change models. Nothing indexes this column (exact KNN at this
    # corpus size), and searches filter `corpus` + `model_key` in a materialized CTE before the
    # distance operator ever sees a row — pgvector errors on comparing different dimensions, so
    # that filter is load-bearing, not cosmetic. Why `halfvec` rather than `vector`, and what it
    # would take to index this one day: `vector_type.py`.
    embedding: Mapped[list[float]] = mapped_column(HalfVector, nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EmbeddingJob(Base):
    """One leased request to add a model vector to a lexical chunk.

    Jobs are durable instead of an in-process asyncio queue: a Console restart releases an
    expired lease, and several replicas can safely claim independent batches. A completed job is
    deleted after its vector reaches ``chunks``; the vector cache itself is the durable proof
    that work completed. Failures stay queued with a retry time and a bounded diagnostic.
    """

    __tablename__ = "embedding_jobs"

    corpus: Mapped[Corpus] = mapped_column(TextBackedStrEnumColumn(Corpus), primary_key=True)
    content_sha: Mapped[str] = mapped_column(Text, primary_key=True)
    chunker_key: Mapped[str] = mapped_column(Text, primary_key=True)
    byte_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_key: Mapped[str] = mapped_column(Text, primary_key=True)
    available_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["corpus", "content_sha", "chunker_key", "byte_start"],
            [
                f"{SCHEMA}.lexical_chunks.corpus",
                f"{SCHEMA}.lexical_chunks.content_sha",
                f"{SCHEMA}.lexical_chunks.chunker_key",
                f"{SCHEMA}.lexical_chunks.byte_start",
            ],
            ondelete="CASCADE",
        ),
        Index("idx_embedding_jobs_ready", "available_at"),
    )


class GitTipEntry(Base):
    """One path at the indexed commit. Replaced wholesale every sync."""

    __tablename__ = "git_tip"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    blob_sha: Mapped[str] = mapped_column(Text, nullable=False)


class GitSyncState(Base):
    """What the branch holds and what `git_tip` holds. One row; `id` is pinned to 1.

    Two halves that become true at different moments, which is why the indexed half is nullable:
    a sweep records `remote_commit` every time it looks, including before anything has ever been
    indexed and on the ticks that decide there is nothing to do, while `commit_sha` only appears
    when a sync completes. They live in one row rather than two tables because they are two facts
    about the same branch and every reader wants both — "is the index behind" is a comparison
    within a row.

    The check keeps the indexed half all-or-nothing: a commit without the regime it was indexed
    under, or without a time, is not a state this can be in.
    """

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
    # What the branch pointed at when a sweep last looked, and when that was. Null only until the
    # first sweep reaches the repository at all, which is the shape of an unreachable remote.
    remote_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_seen_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The indexed half: null together until a first sync completes.
    commit_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunker_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatChunk(Base):
    """One searchable window of a chat session.

    Keyed by its position in the session rather than by its content, because two sessions can
    hold the same exchange verbatim: they are then two windows sharing one cached vector, and a
    search that matches it must be able to say which session each hit came from.
    """

    __tablename__ = "chat_chunks"

    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    window_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_sha: Mapped[str] = mapped_column(Text, nullable=False)
    first_message_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatChunkMessage(Base):
    """This chunk holds these messages, in this order.

    The pointer a hit hands back: a caller reads the real content through the console's own
    conversation tools (`haku/console/tools/conversations.py`) rather than trusting the copy in
    `chunks.text`, which is what the embedder saw and not necessarily what the row says now.
    """

    __tablename__ = "chat_chunk_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "window_no"],
            [f"{SCHEMA}.chat_chunks.session_id", f"{SCHEMA}.chat_chunks.window_no"],
            ondelete="CASCADE",
        ),
        # The reverse direction: which window holds a given message.
        Index("idx_chat_chunk_messages_message", "message_id"),
    )

    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    window_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class ChatSessionState(Base):
    """The shape of one chat session as last indexed, which is what decides re-indexing.

    A session grows, so unlike a git tip there is no single commit to compare against. The
    message count and newest message time are that comparison: a session whose source still
    matches both, under the same regime, is skipped without reading its messages.
    """

    __tablename__ = "chat_sessions"

    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_message_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chunker_key: Mapped[str] = mapped_column(Text, nullable=False)
    model_key: Mapped[str] = mapped_column(Text, nullable=False)
    indexed_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
