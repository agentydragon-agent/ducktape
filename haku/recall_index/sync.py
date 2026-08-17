"""Bring the Git corpus up to a branch tip.

Git chunks are source occurrences; globally-addressed content and model-specific embeddings are
separate durable index layers.  Vectors are committed batch by batch before the tip changes, so a
failed run leaves expensive semantic work reusable while the previous tip remains searchable.
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from dataclasses import dataclass

import pygit2
from more_itertools import batched
from sqlalchemy.ext.asyncio import AsyncSession

from haku.recall_index.chunking import DEFAULT_CHUNK_BUDGET, ChunkBudget, Span, chunk_text, git_chunker_key
from haku.recall_index.content import content_sha
from haku.recall_index.embedder import EMBED_BATCH, Embedder
from haku.recall_index.git_tree import list_tip, read_blob
from haku.recall_index.schema import GitSyncState
from haku.recall_index.store import (
    ContentEmbeddingRow,
    GitChunkRow,
    current_git_state,
    embedded_content,
    git_chunked_blobs,
    git_content_rows,
    insert_content_embeddings,
    insert_git_chunks,
    replace_tip,
)

logger = logging.getLogger(__name__)

# Above this, a blob is data rather than prose: it remains honestly represented in ``git_tip`` but
# has no semantic chunks and therefore cannot match a semantic query.
MAX_BLOB_BYTES = 1 << 20


@dataclass(frozen=True, slots=True)
class AlreadyCurrent:
    commit_sha: str


@dataclass(frozen=True, slots=True)
class SyncReport:
    commit_sha: str
    tip_files: int
    # Kept as source-blob counts for the CLI's existing reporting surface.  A blob is counted as
    # embedded when at least one of its content values needed a vector under this model.
    blobs_embedded: int
    blobs_reused: int
    chunks_written: int
    skipped_binary: int
    skipped_large: int


SyncOutcome = AlreadyCurrent | SyncReport


def is_current(
    state: GitSyncState | None,
    commit_sha: str,
    *,
    branch: str,
    model_key: str,
    budget: ChunkBudget = DEFAULT_CHUNK_BUDGET,
) -> bool:
    """Whether the source revision and complete retrieval regime are already published."""
    return state is not None and (state.commit_sha, state.branch, state.chunker_key, state.model_key) == (
        commit_sha,
        branch,
        git_chunker_key(budget),
        model_key,
    )


async def sync(
    session: AsyncSession,
    repo: pygit2.Repository,
    commit_sha: str,
    *,
    branch: str,
    embedder: Embedder,
    now: datetime.datetime,
    budget: ChunkBudget = DEFAULT_CHUNK_BUDGET,
) -> SyncOutcome:
    """Materialize the tip's source chunks and content embeddings, then publish the tip."""
    regime = git_chunker_key(budget)
    if is_current(
        await current_git_state(session), commit_sha, branch=branch, model_key=embedder.model_key, budget=budget
    ):
        logger.info("haku-state index already at %s", commit_sha)
        return AlreadyCurrent(commit_sha=commit_sha)

    entries = list_tip(repo, commit_sha)
    blob_shas = {entry.blob_sha for entry in entries}
    chunked_blobs = await git_chunked_blobs(session, blob_shas, chunker_key=regime)
    known_rows = await git_content_rows(session, chunked_blobs, chunker_key=regime)

    content_by_sha: dict[str, str] = {}
    blob_content_shas: dict[str, set[str]] = defaultdict(set)
    for blob_sha, address, content in known_rows:
        _record_content(content_by_sha, address, content)
        blob_content_shas[blob_sha].add(address)

    new_chunks: list[GitChunkRow] = []
    skipped_binary = 0
    skipped_large = 0
    for blob_sha in sorted(blob_shas - chunked_blobs):
        data = read_blob(repo, blob_sha)
        if len(data) > MAX_BLOB_BYTES:
            skipped_large += 1
            continue
        try:
            blob_text = data.decode()
        except UnicodeDecodeError:
            skipped_binary += 1
            continue
        for chunk in chunk_text(blob_text, budget):
            address = content_sha(chunk.text)
            _record_content(content_by_sha, address, chunk.text)
            blob_content_shas[blob_sha].add(address)
            new_chunks.append(_git_chunk_row(blob_sha, chunk, address, chunker_key=regime))

    already_embedded = await embedded_content(session, content_by_sha, model_key=embedder.model_key)
    missing = [(address, content) for address, content in content_by_sha.items() if address not in already_embedded]
    embedded_blobs = {
        blob_sha
        for blob_sha, addresses in blob_content_shas.items()
        if any(address not in already_embedded for address in addresses)
    }

    logger.info(
        "haku-state %s: %d files, %d new source chunks, %d content values to embed",
        commit_sha[:12],
        len(entries),
        len(new_chunks),
        len(missing),
    )

    for batch in batched(missing, EMBED_BATCH):
        vectors = await embedder.embed_documents([content for _, content in batch])
        await insert_content_embeddings(
            session,
            [
                ContentEmbeddingRow(
                    content_sha=address, content=content, model_key=embedder.model_key, embedding=vector
                )
                for (address, content), vector in zip(batch, vectors, strict=True)
            ],
        )
        # Content embeddings are unreachable until ``replace_tip`` publishes the source rows.
        # Committing them here makes a failed first sync resume without repaying provider calls.
        await session.commit()

    # New source rows may refer to both freshly inserted and previously embedded content.  This is
    # intentionally after the batch commits: a crash before it lands leaves no half-published tip,
    # and the retry reads the same source chunks but finds all their vectors durable.
    await insert_git_chunks(session, new_chunks)
    await replace_tip(
        session,
        entries,
        commit_sha=commit_sha,
        branch=branch,
        chunker_key=regime,
        model_key=embedder.model_key,
        now=now,
    )
    report = SyncReport(
        commit_sha=commit_sha,
        tip_files=len(entries),
        blobs_embedded=len(embedded_blobs),
        blobs_reused=len(blob_content_shas) - len(embedded_blobs),
        chunks_written=len(new_chunks),
        skipped_binary=skipped_binary,
        skipped_large=skipped_large,
    )
    logger.info("synced haku-state index: %s", report)
    return report


def _record_content(content_by_sha: dict[str, str], address: str, content: str) -> None:
    previous = content_by_sha.setdefault(address, content)
    if previous != content:
        raise AssertionError(f"content address collision: {address}")


def _git_chunk_row(blob_sha: str, chunk: Span, address: str, *, chunker_key: str) -> GitChunkRow:
    return GitChunkRow(
        blob_sha=blob_sha,
        chunker_key=chunker_key,
        byte_start=chunk.byte_start,
        byte_end=chunk.byte_end,
        content_sha=address,
    )
