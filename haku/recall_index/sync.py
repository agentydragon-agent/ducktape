"""Bring one configured Git index's source chunks up to its branch tip.

Git owns source occurrences and their content inputs, not model-specific vectors. A shared worker
embeds newly materialized global content asynchronously, so a slow or unavailable embedder cannot
hold a source revision behind its branch tip.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

import pygit2
from sqlalchemy.ext.asyncio import AsyncSession

from haku.recall_index.chunking import DEFAULT_CHUNK_BUDGET, ChunkBudget, Span, chunk_text, git_chunker_key
from haku.recall_index.content import content_sha
from haku.recall_index.git_tree import list_tip, read_blob
from haku.recall_index.schema import GitSyncState
from haku.recall_index.store import (
    ContentRow,
    GitChunkRow,
    current_git_state,
    git_chunked_blobs,
    insert_contents,
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
    chunks_written: int
    contents_materialized: int
    skipped_binary: int
    skipped_large: int


SyncOutcome = AlreadyCurrent | SyncReport


def is_current(
    state: GitSyncState | None, commit_sha: str, *, branch: str, budget: ChunkBudget = DEFAULT_CHUNK_BUDGET
) -> bool:
    """Whether the source revision and complete retrieval regime are already published."""
    return state is not None and (state.commit_sha, state.branch, state.chunker_key) == (
        commit_sha,
        branch,
        git_chunker_key(budget),
    )


async def sync(
    session: AsyncSession,
    repo: pygit2.Repository,
    commit_sha: str,
    *,
    index_id: str,
    branch: str,
    now: datetime.datetime,
    budget: ChunkBudget = DEFAULT_CHUNK_BUDGET,
) -> SyncOutcome:
    """Materialize and publish the tip's chunks; the shared worker embeds their content later."""
    regime = git_chunker_key(budget)
    if is_current(await current_git_state(session, index_id), commit_sha, branch=branch, budget=budget):
        logger.info("Git index %s already at %s", index_id, commit_sha)
        return AlreadyCurrent(commit_sha=commit_sha)

    entries = list_tip(repo, commit_sha)
    blob_shas = {entry.blob_sha for entry in entries}
    chunked_blobs = await git_chunked_blobs(session, index_id, blob_shas, chunker_key=regime)
    content_by_sha: dict[str, str] = {}
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
            new_chunks.append(_git_chunk_row(index_id, blob_sha, chunk, address, chunker_key=regime))

    logger.info(
        "Git index %s at %s: %d files, %d new source chunks, %d content values queued",
        index_id,
        commit_sha[:12],
        len(entries),
        len(new_chunks),
        len(content_by_sha),
    )
    await insert_contents(
        session, (ContentRow(content_sha=address, content=content) for address, content in content_by_sha.items())
    )
    await insert_git_chunks(session, new_chunks)
    await replace_tip(
        session, entries, index_id=index_id, commit_sha=commit_sha, branch=branch, chunker_key=regime, now=now
    )
    report = SyncReport(
        commit_sha=commit_sha,
        tip_files=len(entries),
        chunks_written=len(new_chunks),
        contents_materialized=len(content_by_sha),
        skipped_binary=skipped_binary,
        skipped_large=skipped_large,
    )
    logger.info("synced Git index %s: %s", index_id, report)
    return report


def _record_content(content_by_sha: dict[str, str], address: str, content: str) -> None:
    previous = content_by_sha.setdefault(address, content)
    if previous != content:
        raise AssertionError(f"content address collision: {address}")


def _git_chunk_row(index_id: str, blob_sha: str, chunk: Span, address: str, *, chunker_key: str) -> GitChunkRow:
    return GitChunkRow(
        index_id=index_id,
        blob_sha=blob_sha,
        chunker_key=chunker_key,
        byte_start=chunk.byte_start,
        byte_end=chunk.byte_end,
        content_sha=address,
    )
