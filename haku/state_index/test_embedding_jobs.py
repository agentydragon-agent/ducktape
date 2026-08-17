"""The durable hand-off from lexical chunks to model-specific vector work."""

from __future__ import annotations

import datetime

import pytest_bazel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from haku.state_index.embedding_jobs import (
    LexicalChunkRow,
    claim_embedding_jobs,
    complete_embedding_jobs,
    enqueue_missing_embeddings,
    materialize_lexical_chunks,
    retry_embedding_jobs,
)
from haku.state_index.schema import Chunk, Corpus, EmbeddingJob, LexicalChunk

_NOW = datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC)
_ROW = LexicalChunkRow(
    corpus=Corpus.GIT,
    content_sha="a" * 40,
    chunker_key='{"max_bytes":3000,"target_bytes":1500,"version":1}',
    byte_start=0,
    byte_end=12,
    text="alpha beta\n",
)


async def test_materialization_and_queueing_are_idempotent(session: AsyncSession) -> None:
    await materialize_lexical_chunks(session, [_ROW], now=_NOW)
    assert await enqueue_missing_embeddings(session, [_ROW], model_key="fake-v1", now=_NOW) == 1
    # A second source sweep names the same canonical text and the existing outstanding job.
    await materialize_lexical_chunks(session, [_ROW], now=_NOW + datetime.timedelta(minutes=1))
    assert await enqueue_missing_embeddings(session, [_ROW], model_key="fake-v1", now=_NOW) == 0
    await session.commit()

    assert (await session.execute(select(func.count()).select_from(LexicalChunk))).scalar_one() == 1
    assert (await session.execute(select(func.count()).select_from(EmbeddingJob))).scalar_one() == 1


async def test_a_lease_prevents_concurrent_claim_and_can_expire(session: AsyncSession) -> None:
    await materialize_lexical_chunks(session, [_ROW], now=_NOW)
    await enqueue_missing_embeddings(session, [_ROW], model_key="fake-v1", now=_NOW)
    await session.commit()

    first = await claim_embedding_jobs(session, now=_NOW, limit=32, lease_for=datetime.timedelta(minutes=1))
    await session.commit()
    assert [job.row.text for job in first] == ["alpha beta\n"]

    assert (
        await claim_embedding_jobs(
            session, now=_NOW + datetime.timedelta(seconds=30), limit=32, lease_for=datetime.timedelta(minutes=1)
        )
        == []
    )
    reclaimed = await claim_embedding_jobs(
        session, now=_NOW + datetime.timedelta(minutes=1), limit=32, lease_for=datetime.timedelta(minutes=1)
    )
    assert [job.model_key for job in reclaimed] == ["fake-v1"]


async def test_completed_job_writes_the_existing_vector_cache_and_disappears(session: AsyncSession) -> None:
    await materialize_lexical_chunks(session, [_ROW], now=_NOW)
    await enqueue_missing_embeddings(session, [_ROW], model_key="fake-v1", now=_NOW)
    jobs = await claim_embedding_jobs(session, now=_NOW, limit=1, lease_for=datetime.timedelta(minutes=1))
    await complete_embedding_jobs(session, jobs, [[0.5, 0.5]], now=_NOW)
    await session.commit()

    assert (await session.execute(select(func.count()).select_from(EmbeddingJob))).scalar_one() == 0
    (chunk,) = (await session.execute(select(Chunk))).scalars().all()
    assert (chunk.corpus, chunk.content_sha, chunk.chunker_key, chunk.byte_start, chunk.model_key) == (
        _ROW.corpus,
        _ROW.content_sha,
        _ROW.chunker_key,
        _ROW.byte_start,
        "fake-v1",
    )
    assert chunk.text == _ROW.text

    # Completion is represented by the vector cache, so a later source sweep requests no work.
    assert await enqueue_missing_embeddings(session, [_ROW], model_key="fake-v1", now=_NOW) == 0


async def test_failed_job_is_released_for_a_later_retry(session: AsyncSession) -> None:
    await materialize_lexical_chunks(session, [_ROW], now=_NOW)
    await enqueue_missing_embeddings(session, [_ROW], model_key="fake-v1", now=_NOW)
    jobs = await claim_embedding_jobs(session, now=_NOW, limit=1, lease_for=datetime.timedelta(minutes=1))
    await retry_embedding_jobs(
        session, jobs, now=_NOW, retry_after=datetime.timedelta(minutes=2), error="temporary embedding endpoint failure"
    )
    await session.commit()

    assert (
        await claim_embedding_jobs(
            session, now=_NOW + datetime.timedelta(minutes=1), limit=1, lease_for=datetime.timedelta(minutes=1)
        )
        == []
    )
    retried = await claim_embedding_jobs(
        session, now=_NOW + datetime.timedelta(minutes=2), limit=1, lease_for=datetime.timedelta(minutes=1)
    )
    assert len(retried) == 1
    job = await session.get(
        EmbeddingJob,
        {
            "corpus": _ROW.corpus,
            "content_sha": _ROW.content_sha,
            "chunker_key": _ROW.chunker_key,
            "byte_start": _ROW.byte_start,
            "model_key": "fake-v1",
        },
    )
    assert job is not None
    assert (job.attempts, job.last_error) == (1, "temporary embedding endpoint failure")


if __name__ == "__main__":
    pytest_bazel.main()
