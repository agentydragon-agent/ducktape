"""Durable lexical-chunk materialization and model-specific embedding work.

Source synchronizers own discovering text. They write :class:`LexicalChunk` rows and enqueue
missing model vectors, then may return immediately. A separate worker claims a bounded lease from
``embedding_jobs`` and writes the existing ``chunks`` vector cache only after the embedding
endpoint returns.

There is deliberately no in-memory queue here. The database is the hand-off: it survives a
Console restart, allows several replicas to work without duplicate leases, and makes retry state
observable.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from haku.state_index.embedder import EMBED_BATCH, Embedder
from haku.state_index.schema import Chunk, Corpus, EmbeddingJob, LexicalChunk
from haku.state_index.store import ChunkRow, insert_chunks


@dataclass(frozen=True, slots=True)
class LexicalChunkRow:
    """Canonical chunk text to retain independently of an embedding model."""

    corpus: Corpus
    content_sha: str
    chunker_key: str
    byte_start: int
    byte_end: int
    text: str


@dataclass(frozen=True, slots=True)
class ClaimedEmbeddingJob:
    """A leased job plus the canonical text that the endpoint should embed."""

    row: LexicalChunkRow
    model_key: str


@dataclass(frozen=True, slots=True)
class EmbeddingBatchReport:
    """One bounded worker pass, suitable for compact operational logging."""

    claimed: int
    completed: int
    retried: int


async def materialize_lexical_chunks(
    session: AsyncSession, rows: Sequence[LexicalChunkRow], *, now: datetime.datetime
) -> None:
    """Upsert canonical text, refreshing liveness without rewriting immutable content.

    The four identifying fields address the exact byte span that the chunker produced. A conflict
    therefore means the text is already known; updating it would hide a broken content hash or
    chunker rather than repair anything.
    """
    if not rows:
        return
    statement = pg_insert(LexicalChunk).on_conflict_do_update(
        index_elements=["corpus", "content_sha", "chunker_key", "byte_start"],
        set_={"last_seen_at": pg_insert(LexicalChunk).excluded.last_seen_at},
    )
    await session.execute(statement, [{**asdict(row), "last_seen_at": now} for row in rows])


async def enqueue_missing_embeddings(
    session: AsyncSession, rows: Sequence[LexicalChunkRow], *, model_key: str, now: datetime.datetime
) -> int:
    """Durably request vectors not already in the model-specific cache.

    Completion is represented by the vector cache row, not a retained success job. The unique job
    key makes concurrent source sweeps coalesce into one request; an expired lease remains the
    same job and is reclaimed by a worker rather than duplicated.
    """
    inserted = 0
    for row in rows:
        has_vector = await session.scalar(
            select(Chunk.content_sha)
            .where(Chunk.corpus == row.corpus)
            .where(Chunk.content_sha == row.content_sha)
            .where(Chunk.chunker_key == row.chunker_key)
            .where(Chunk.byte_start == row.byte_start)
            .where(Chunk.model_key == model_key)
            .limit(1)
        )
        if has_vector is not None:
            continue
        result = await session.execute(
            pg_insert(EmbeddingJob)
            .values(
                corpus=row.corpus,
                content_sha=row.content_sha,
                chunker_key=row.chunker_key,
                byte_start=row.byte_start,
                model_key=model_key,
                available_at=now,
                attempts=0,
            )
            .on_conflict_do_nothing()
        )
        inserted += result.rowcount or 0
    return inserted


async def claim_embedding_jobs(
    session: AsyncSession, *, now: datetime.datetime, limit: int, lease_for: datetime.timedelta
) -> list[ClaimedEmbeddingJob]:
    """Lease up to ``limit`` ready jobs without holding a transaction over the network call."""
    if limit <= 0:
        raise ValueError("embedding job claim limit must be positive")
    if lease_for <= datetime.timedelta():
        raise ValueError("embedding job lease must be positive")

    ready = (
        select(EmbeddingJob, LexicalChunk)
        .join(
            LexicalChunk,
            and_(
                LexicalChunk.corpus == EmbeddingJob.corpus,
                LexicalChunk.content_sha == EmbeddingJob.content_sha,
                LexicalChunk.chunker_key == EmbeddingJob.chunker_key,
                LexicalChunk.byte_start == EmbeddingJob.byte_start,
            ),
        )
        .where(EmbeddingJob.available_at <= now)
        .where(or_(EmbeddingJob.lease_expires_at.is_(None), EmbeddingJob.lease_expires_at <= now))
        .order_by(EmbeddingJob.available_at, EmbeddingJob.attempts, EmbeddingJob.content_sha, EmbeddingJob.byte_start)
        .limit(limit)
        .with_for_update(skip_locked=True, of=EmbeddingJob)
    )
    pairs = (await session.execute(ready)).all()
    lease_expires_at = now + lease_for
    claimed: list[ClaimedEmbeddingJob] = []
    for job, chunk in pairs:
        job.lease_expires_at = lease_expires_at
        claimed.append(
            ClaimedEmbeddingJob(
                row=LexicalChunkRow(
                    corpus=chunk.corpus,
                    content_sha=chunk.content_sha,
                    chunker_key=chunk.chunker_key,
                    byte_start=chunk.byte_start,
                    byte_end=chunk.byte_end,
                    text=chunk.text,
                ),
                model_key=job.model_key,
            )
        )
    return claimed


def _job_match(job: ClaimedEmbeddingJob):
    row = job.row
    return and_(
        EmbeddingJob.corpus == row.corpus,
        EmbeddingJob.content_sha == row.content_sha,
        EmbeddingJob.chunker_key == row.chunker_key,
        EmbeddingJob.byte_start == row.byte_start,
        EmbeddingJob.model_key == job.model_key,
    )


async def complete_embedding_jobs(
    session: AsyncSession,
    jobs: Sequence[ClaimedEmbeddingJob],
    vectors: Sequence[list[float]],
    *,
    now: datetime.datetime,
) -> None:
    """Store returned vectors then delete exactly the completed durable jobs."""
    if len(jobs) != len(vectors):
        raise ValueError("embedding result count did not match the claimed job count")
    rows = [
        ChunkRow(
            corpus=job.row.corpus,
            content_sha=job.row.content_sha,
            chunker_key=job.row.chunker_key,
            model_key=job.model_key,
            byte_start=job.row.byte_start,
            byte_end=job.row.byte_end,
            text=job.row.text,
            embedding=vector,
        )
        for job, vector in zip(jobs, vectors, strict=True)
    ]
    await insert_chunks(session, rows, now=now)
    for job in jobs:
        await session.execute(delete(EmbeddingJob).where(_job_match(job)))


async def retry_embedding_jobs(
    session: AsyncSession,
    jobs: Sequence[ClaimedEmbeddingJob],
    *,
    now: datetime.datetime,
    retry_after: datetime.timedelta,
    error: str,
) -> None:
    """Release failed jobs for a later attempt, retaining a bounded operational diagnostic."""
    if retry_after < datetime.timedelta():
        raise ValueError("embedding retry delay cannot be negative")
    message = error.strip()[:512] or "embedding request failed"
    for job in jobs:
        await session.execute(
            update(EmbeddingJob)
            .where(_job_match(job))
            .values(
                attempts=EmbeddingJob.attempts + 1,
                available_at=now + retry_after,
                lease_expires_at=None,
                last_error=message,
            )
        )


async def run_embedding_batch(
    sessions: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    *,
    now: datetime.datetime,
    retry_after: datetime.timedelta,
    lease_for: datetime.timedelta,
    limit: int = EMBED_BATCH,
) -> EmbeddingBatchReport:
    """Claim, embed, and complete at most one durable batch.

    The claim commits before the HTTP call, so no database transaction or row lock stays open
    while Ollama works. On a failure the same jobs are released with a retry time before the
    exception is returned to the maintenance loop for logging.
    """
    async with sessions() as session:
        jobs = await claim_embedding_jobs(session, now=now, limit=limit, lease_for=lease_for)
        await session.commit()
    if not jobs:
        return EmbeddingBatchReport(claimed=0, completed=0, retried=0)

    try:
        vectors = await embedder.embed_documents([job.row.text for job in jobs])
        if len(vectors) != len(jobs):
            raise RuntimeError("embedding endpoint returned a different number of vectors than documents")
    except Exception as error:
        async with sessions() as session:
            await retry_embedding_jobs(
                session, jobs, now=now, retry_after=retry_after, error=f"{type(error).__name__}: {error}"
            )
            await session.commit()
        raise

    async with sessions() as session:
        await complete_embedding_jobs(session, jobs, vectors, now=now)
        await session.commit()
    return EmbeddingBatchReport(claimed=len(jobs), completed=len(jobs), retried=0)
