"""Database operations over Haku's content-addressed semantic index.

Source-specific rows describe where content occurred.  ``contents`` holds the exact normalized
text globally, and ``content_embeddings`` holds that text's vector for one embedding model.  This
keeps provenance local while making semantic materialization reusable across every corpus.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from haku.recall_index.chat_corpus import MessageChunk, chat_chunker_key
from haku.recall_index.chunking import DEFAULT_CHUNK_BUDGET, ChunkBudget, git_chunker_key
from haku.recall_index.git_tree import TipEntry
from haku.recall_index.schema import (
    SCHEMA,
    Base,
    ChatChunk,
    ChatChunkMessage,
    ChatSessionState,
    Content,
    ContentEmbedding,
    Corpus,
    GitChunk,
    GitSyncState,
    GitTipEntry,
)

# Materializing candidate rows before applying the distance operator is load-bearing: embeddings
# for different model keys may have different dimensions, and pgvector refuses to compare them.
_GIT_SEARCH_SQL = text(f"""
    WITH candidates AS MATERIALIZED (
        SELECT t.path, t.blob_sha, g.byte_start, g.byte_end, c.content AS text, e.embedding
        FROM {SCHEMA}.git_tip t
        JOIN {SCHEMA}.git_chunks g ON g.blob_sha = t.blob_sha
        JOIN {SCHEMA}.contents c ON c.content_sha = g.content_sha
        JOIN {SCHEMA}.content_embeddings e ON e.content_sha = c.content_sha
        WHERE g.chunker_key = :chunker_key
          AND e.model_key = :model_key
          AND (CAST(:path_prefix AS text) IS NULL OR starts_with(t.path, CAST(:path_prefix AS text)))
    )
    SELECT path, blob_sha, byte_start, byte_end, text,
           1 - (embedding <=> CAST(:query AS halfvec)) AS score
    FROM candidates
    ORDER BY embedding <=> CAST(:query AS halfvec)
    LIMIT :limit
""")

_CHAT_SEARCH_SQL = text(f"""
    WITH candidates AS MATERIALIZED (
        SELECT w.session_id, w.window_no, w.first_message_at, w.last_message_at,
               c.content AS text, e.embedding
        FROM {SCHEMA}.chat_chunks w
        JOIN {SCHEMA}.chat_sessions s ON s.session_id = w.session_id
        JOIN {SCHEMA}.contents c ON c.content_sha = w.content_sha
        JOIN {SCHEMA}.content_embeddings e ON e.content_sha = c.content_sha
        WHERE s.chunker_key = :chunker_key
          AND s.model_key = :model_key
          AND e.model_key = :model_key
          AND (CAST(:session_id AS uuid) IS NULL OR w.session_id = CAST(:session_id AS uuid))
    ), ranked AS (
        SELECT session_id, window_no, first_message_at, last_message_at, text,
               1 - (embedding <=> CAST(:query AS halfvec)) AS score
        FROM candidates
        ORDER BY embedding <=> CAST(:query AS halfvec)
        LIMIT :limit
    )
    SELECT ranked.*,
           ARRAY(
               SELECT m.message_id FROM {SCHEMA}.chat_chunk_messages m
               WHERE m.session_id = ranked.session_id AND m.window_no = ranked.window_no
               ORDER BY m.ordinal
           ) AS message_ids
    FROM ranked
    ORDER BY score DESC
""")


@dataclass(frozen=True, slots=True)
class GitSearchHit:
    path: str
    blob_sha: str
    byte_start: int
    byte_end: int
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class ChatSearchHit:
    session_id: UUID
    window_no: int
    message_ids: list[UUID]
    first_message_at: datetime.datetime
    last_message_at: datetime.datetime
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class GitIndexSummary:
    files: int
    chunks: int


@dataclass(frozen=True, slots=True)
class ChunkCounts:
    current: int
    superseded: int


@dataclass(frozen=True, slots=True)
class ChatIndexSummary:
    sessions: int
    chunks: int
    last_indexed_at: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class ContentEmbeddingRow:
    """One exact content value and the vector a model produced for it."""

    content_sha: str
    content: str
    model_key: str
    embedding: list[float]


@dataclass(frozen=True, slots=True)
class GitChunkRow:
    """One source occurrence of globally-addressed content in a Git blob."""

    blob_sha: str
    chunker_key: str
    byte_start: int
    byte_end: int
    content_sha: str


def chunker_key_for(corpus: Corpus, budget: ChunkBudget = DEFAULT_CHUNK_BUDGET) -> str:
    """Which chunker regime is current for a corpus."""
    match corpus:
        case Corpus.GIT:
            return git_chunker_key(budget)
        case Corpus.CHAT:
            return chat_chunker_key(budget)


async def ensure_schema(engine: AsyncEngine) -> None:
    """Create the extension, schema, and tables for local evaluation and tests."""
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        await connection.run_sync(Base.metadata.create_all)


async def embedded_content(session: AsyncSession, content_shas: Iterable[str], *, model_key: str) -> set[str]:
    """Which globally-addressed content values already have a vector for ``model_key``."""
    addresses = sorted(set(content_shas))
    if not addresses:
        return set()
    result = await session.execute(
        select(ContentEmbedding.content_sha)
        .where(ContentEmbedding.content_sha.in_(addresses))
        .where(ContentEmbedding.model_key == model_key)
    )
    return set(result.scalars())


async def git_chunked_blobs(session: AsyncSession, blob_shas: Iterable[str], *, chunker_key: str) -> set[str]:
    """Which Git blobs already have their source occurrences under this chunker regime."""
    addresses = sorted(set(blob_shas))
    if not addresses:
        return set()
    result = await session.execute(
        select(GitChunk.blob_sha)
        .where(GitChunk.blob_sha.in_(addresses))
        .where(GitChunk.chunker_key == chunker_key)
        .distinct()
    )
    return set(result.scalars())


async def git_content_rows(
    session: AsyncSession, blob_shas: Iterable[str], *, chunker_key: str
) -> list[tuple[str, str, str]]:
    """Existing Git source occurrences paired with their exact global content."""
    addresses = sorted(set(blob_shas))
    if not addresses:
        return []
    result = await session.execute(
        select(GitChunk.blob_sha, Content.content_sha, Content.content)
        .join(Content, Content.content_sha == GitChunk.content_sha)
        .where(GitChunk.blob_sha.in_(addresses))
        .where(GitChunk.chunker_key == chunker_key)
    )
    return list(result.tuples())


def _content_map(rows: Iterable[tuple[str, str]]) -> dict[str, str]:
    content_by_sha: dict[str, str] = {}
    for address, content in rows:
        previous = content_by_sha.setdefault(address, content)
        if previous != content:
            raise AssertionError(f"content address collision: {address}")
    return content_by_sha


async def insert_content_embeddings(session: AsyncSession, rows: Sequence[ContentEmbeddingRow]) -> None:
    """Persist content and vectors, retaining an existing vector as the authoritative result.

    The two inserts are conflict-safe, so independently-running sync workers cannot duplicate
    durable rows.  Callers de-duplicate misses before asking an embedding provider; a rare race
    may still compute the same vector twice, but cannot publish two conflicting representations.
    """
    if not rows:
        return
    content_by_sha = _content_map((row.content_sha, row.content) for row in rows)
    existing = await session.execute(
        select(Content.content_sha, Content.content).where(Content.content_sha.in_(content_by_sha))
    )
    for address, content in existing:
        if content_by_sha[address] != content:
            raise AssertionError(f"content address collision: {address}")
    content_statement = pg_insert(Content).on_conflict_do_nothing(index_elements=["content_sha"])
    await session.execute(
        content_statement, [{"content_sha": address, "content": content} for address, content in content_by_sha.items()]
    )
    embedding_statement = pg_insert(ContentEmbedding).on_conflict_do_nothing(
        index_elements=["content_sha", "model_key"]
    )
    await session.execute(
        embedding_statement,
        [{"content_sha": row.content_sha, "model_key": row.model_key, "embedding": row.embedding} for row in rows],
    )


async def insert_git_chunks(session: AsyncSession, rows: Sequence[GitChunkRow]) -> None:
    """Persist Git source occurrences after their content rows exist."""
    if not rows:
        return
    statement = pg_insert(GitChunk).on_conflict_do_nothing(index_elements=["blob_sha", "chunker_key", "byte_start"])
    await session.execute(
        statement,
        [
            {
                "blob_sha": row.blob_sha,
                "chunker_key": row.chunker_key,
                "byte_start": row.byte_start,
                "byte_end": row.byte_end,
                "content_sha": row.content_sha,
            }
            for row in rows
        ],
    )


async def replace_tip(
    session: AsyncSession,
    entries: Sequence[TipEntry],
    *,
    commit_sha: str,
    branch: str,
    chunker_key: str,
    model_key: str,
    now: datetime.datetime,
) -> None:
    """Atomically make one Git tree the searchable tip after its content is materialized."""
    await session.execute(delete(GitTipEntry))
    if entries:
        await session.execute(
            insert(GitTipEntry), [{"path": entry.path, "blob_sha": entry.blob_sha} for entry in entries]
        )
    indexed = {
        "commit_sha": commit_sha,
        "branch": branch,
        "chunker_key": chunker_key,
        "model_key": model_key,
        "synced_at": now,
    }
    await session.execute(
        pg_insert(GitSyncState).values(id=1, **indexed).on_conflict_do_update(index_elements=["id"], set_=indexed)
    )


async def current_git_state(session: AsyncSession) -> GitSyncState | None:
    return await session.get(GitSyncState, 1)


async def record_remote_tip(session: AsyncSession, commit_sha: str, *, branch: str, now: datetime.datetime) -> None:
    values = {"id": 1, "branch": branch, "remote_commit": commit_sha, "remote_seen_at": now}
    await session.execute(
        pg_insert(GitSyncState)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["id"], set_={"branch": branch, "remote_commit": commit_sha, "remote_seen_at": now}
        )
    )


async def search_git(
    session: AsyncSession,
    embedding: Sequence[float],
    *,
    model_key: str,
    limit: int,
    path_prefix: str | None = None,
    budget: ChunkBudget = DEFAULT_CHUNK_BUDGET,
) -> list[GitSearchHit]:
    result = await session.execute(
        _GIT_SEARCH_SQL,
        {
            "chunker_key": chunker_key_for(Corpus.GIT, budget),
            "model_key": model_key,
            "path_prefix": path_prefix,
            "query": f"[{','.join(map(str, embedding))}]",
            "limit": limit,
        },
    )
    return [GitSearchHit(**row) for row in result.mappings()]


async def read_indexed_text(
    session: AsyncSession, path: str, *, model_key: str, budget: ChunkBudget = DEFAULT_CHUNK_BUDGET
) -> str | None:
    """The current Git chunk contents at ``path``, concatenated in source-byte order."""
    result = await session.execute(
        select(Content.content)
        .join(GitChunk, GitChunk.content_sha == Content.content_sha)
        .join(GitTipEntry, GitTipEntry.blob_sha == GitChunk.blob_sha)
        .join(
            ContentEmbedding,
            (ContentEmbedding.content_sha == Content.content_sha) & (ContentEmbedding.model_key == model_key),
        )
        .where(GitTipEntry.path == path)
        .where(GitChunk.chunker_key == chunker_key_for(Corpus.GIT, budget))
        .order_by(GitChunk.byte_start)
    )
    chunks = list(result.scalars())
    return "".join(chunks) if chunks else None


async def chat_session_states(session: AsyncSession) -> dict[UUID, ChatSessionState]:
    result = await session.execute(select(ChatSessionState))
    return {state.session_id: state for state in result.scalars()}


async def replace_chat_session(
    session: AsyncSession,
    session_id: UUID,
    chunks: Sequence[MessageChunk],
    *,
    message_count: int,
    last_message_at: datetime.datetime,
    chunker_key: str,
    model_key: str,
    now: datetime.datetime,
) -> None:
    """Replace one session's source windows after their global content has been materialized."""
    await session.execute(delete(ChatChunk).where(ChatChunk.session_id == session_id))
    if chunks:
        await session.execute(
            insert(ChatChunk),
            [
                {
                    "session_id": session_id,
                    "window_no": chunk.window_no,
                    "content_sha": chunk.content_sha,
                    "first_message_at": chunk.first_message_at,
                    "last_message_at": chunk.last_message_at,
                }
                for chunk in chunks
            ],
        )
        await session.execute(
            insert(ChatChunkMessage),
            [
                {"session_id": session_id, "window_no": chunk.window_no, "ordinal": ordinal, "message_id": message_id}
                for chunk in chunks
                for ordinal, message_id in enumerate(chunk.message_ids)
            ],
        )
    state = {
        "session_id": session_id,
        "message_count": message_count,
        "last_message_at": last_message_at,
        "chunker_key": chunker_key,
        "model_key": model_key,
        "indexed_at": now,
    }
    await session.execute(
        pg_insert(ChatSessionState).values(**state).on_conflict_do_update(index_elements=["session_id"], set_=state)
    )


async def forget_chat_sessions(session: AsyncSession, session_ids: Sequence[UUID]) -> None:
    if not session_ids:
        return
    await session.execute(delete(ChatChunk).where(ChatChunk.session_id.in_(session_ids)))
    await session.execute(delete(ChatSessionState).where(ChatSessionState.session_id.in_(session_ids)))


async def search_chat(
    session: AsyncSession,
    embedding: Sequence[float],
    *,
    model_key: str,
    limit: int,
    session_id: UUID | None = None,
    budget: ChunkBudget = DEFAULT_CHUNK_BUDGET,
) -> list[ChatSearchHit]:
    result = await session.execute(
        _CHAT_SEARCH_SQL,
        {
            "chunker_key": chunker_key_for(Corpus.CHAT, budget),
            "model_key": model_key,
            "session_id": session_id,
            "query": f"[{','.join(map(str, embedding))}]",
            "limit": limit,
        },
    )
    return [ChatSearchHit(**row) for row in result.mappings()]


async def git_index_summary(
    session: AsyncSession, *, model_key: str, budget: ChunkBudget = DEFAULT_CHUNK_BUDGET
) -> GitIndexSummary:
    files = (await session.execute(select(func.count()).select_from(GitTipEntry))).scalar_one()
    chunks = (
        await session.execute(
            select(func.count())
            .select_from(GitTipEntry)
            .join(GitChunk, GitChunk.blob_sha == GitTipEntry.blob_sha)
            .join(
                ContentEmbedding,
                (ContentEmbedding.content_sha == GitChunk.content_sha) & (ContentEmbedding.model_key == model_key),
            )
            .where(GitChunk.chunker_key == chunker_key_for(Corpus.GIT, budget))
        )
    ).scalar_one()
    return GitIndexSummary(files=files, chunks=chunks)


async def chunk_counts(
    session: AsyncSession, corpus: Corpus, *, model_key: str, budget: ChunkBudget = DEFAULT_CHUNK_BUDGET
) -> ChunkCounts:
    """Count source occurrences reachable under a complete current retrieval regime."""
    match corpus:
        case Corpus.GIT:
            total = (await session.execute(select(func.count()).select_from(GitChunk))).scalar_one()
            current = (
                await session.execute(
                    select(func.count())
                    .select_from(GitChunk)
                    .join(
                        ContentEmbedding,
                        (ContentEmbedding.content_sha == GitChunk.content_sha)
                        & (ContentEmbedding.model_key == model_key),
                    )
                    .where(GitChunk.chunker_key == chunker_key_for(Corpus.GIT, budget))
                )
            ).scalar_one()
        case Corpus.CHAT:
            total = (await session.execute(select(func.count()).select_from(ChatChunk))).scalar_one()
            current = (
                await session.execute(
                    select(func.count())
                    .select_from(ChatChunk)
                    .join(ChatSessionState, ChatSessionState.session_id == ChatChunk.session_id)
                    .join(
                        ContentEmbedding,
                        (ContentEmbedding.content_sha == ChatChunk.content_sha)
                        & (ContentEmbedding.model_key == model_key),
                    )
                    .where(ChatSessionState.chunker_key == chunker_key_for(Corpus.CHAT, budget))
                    .where(ChatSessionState.model_key == model_key)
                )
            ).scalar_one()
    return ChunkCounts(current=current, superseded=total - current)


async def chat_index_summary(session: AsyncSession) -> ChatIndexSummary:
    sessions, last_indexed_at = (
        await session.execute(select(func.count(), func.max(ChatSessionState.indexed_at)))
    ).one()
    chunks = (await session.execute(select(func.count()).select_from(ChatChunk))).scalar_one()
    return ChatIndexSummary(sessions=sessions, chunks=chunks, last_indexed_at=last_indexed_at)
