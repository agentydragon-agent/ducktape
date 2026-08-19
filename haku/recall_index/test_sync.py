"""The index's load-bearing invariants: only the tip is searchable, and the cache outlives it."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from pathlib import Path

import pygit2
import pytest
import pytest_bazel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from haku.recall_index.content import content_sha
from haku.recall_index.embedder import EMBED_BATCH
from haku.recall_index.fake_embedder import ExplodingEmbedder, FakeEmbedder
from haku.recall_index.query import query_git
from haku.recall_index.schema import ContentEmbedding, IndexType
from haku.recall_index.store import current_git_state, read_indexed_text, register_index
from haku.recall_index.sync import AlreadyCurrent, SyncOutcome, SyncReport, sync

_AUTHOR = pygit2.Signature("Test", "test@example.com")
_NOW = datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)
_GIT_INDEX = "test-git"


@pytest.fixture
def repo(tmp_path: Path) -> pygit2.Repository:
    return pygit2.init_repository(str(tmp_path / "repo.git"), bare=True, initial_head="main")


def commit(repo: pygit2.Repository, files: dict[str, str]) -> str:
    index = pygit2.Index()
    for path, content in files.items():
        index.add(pygit2.IndexEntry(path, repo.create_blob(content.encode()), pygit2.enums.FileMode.BLOB))
    parents = [] if repo.head_is_unborn else [str(repo.references["refs/heads/main"].target)]
    return str(repo.create_commit("refs/heads/main", _AUTHOR, _AUTHOR, "c", index.write_tree(repo), parents))


async def run_sync(
    session: AsyncSession,
    repo: pygit2.Repository,
    commit_sha: str,
    embedder: FakeEmbedder,
    *,
    index_id: str = _GIT_INDEX,
) -> SyncOutcome:
    await register_index(session, index_id, index_type=IndexType.GIT, source_id=f"{index_id}-source")
    outcome = await sync(session, repo, commit_sha, index_id=index_id, branch="main", embedder=embedder, now=_NOW)
    await session.commit()
    return outcome


def as_report(outcome: SyncOutcome) -> SyncReport:
    """Narrow to the did-work variant, failing the test if the sync took the early-out."""
    assert isinstance(outcome, SyncReport)
    return outcome


async def find(
    session: AsyncSession,
    embedder: FakeEmbedder,
    query: str,
    *,
    index_id: str = _GIT_INDEX,
    path_prefix: str | None = None,
):
    return await query_git(session, embedder, query, index_id=index_id, limit=5, path_prefix=path_prefix)


async def test_search_returns_the_matching_path(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    head = commit(repo, {"notes/a.md": "all about alpha", "notes/b.md": "beta beta beta", "c.md": "gamma"})
    await run_sync(session, repo, head, embedder)

    hits = await find(session, embedder, "beta")

    assert hits[0].path == "notes/b.md"
    assert hits[0].score > 0


async def test_path_prefix_narrows_the_search(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    head = commit(repo, {"notes/a.md": "beta here", "other/b.md": "beta beta beta"})
    await run_sync(session, repo, head, embedder)

    hits = await find(session, embedder, "beta", path_prefix="notes/")

    assert [hit.path for hit in hits] == ["notes/a.md"]


async def test_two_git_indexes_share_vectors_but_not_occurrences(
    session: AsyncSession, tmp_path: Path, embedder: FakeEmbedder
) -> None:
    """The future read boundary is real in storage before an API is allowed to expose it."""
    first = pygit2.init_repository(str(tmp_path / "first.git"), bare=True, initial_head="main")
    second = pygit2.init_repository(str(tmp_path / "second.git"), bare=True, initial_head="main")
    await register_index(session, "first", index_type=IndexType.GIT, source_id="first-source")
    await register_index(session, "second", index_type=IndexType.GIT, source_id="second-source")
    await session.commit()

    await run_sync(session, first, commit(first, {"a.md": "shared alpha"}), embedder, index_id="first")
    await run_sync(session, second, commit(second, {"b.md": "shared beta"}), embedder, index_id="second")

    assert [hit.path for hit in await find(session, embedder, "shared", index_id="first")] == ["a.md"]
    assert [hit.path for hit in await find(session, embedder, "shared", index_id="second")] == ["b.md"]
    first_state = await current_git_state(session, "first")
    second_state = await current_git_state(session, "second")
    assert first_state is not None
    assert first_state.commit_sha is not None
    assert second_state is not None
    assert second_state.commit_sha is not None


async def test_deleted_content_becomes_unreachable(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    await run_sync(session, repo, commit(repo, {"keep.md": "alpha", "gone.md": "zeta zeta"}), embedder)
    await run_sync(session, repo, commit(repo, {"keep.md": "alpha"}), embedder)

    assert [hit.path for hit in await find(session, embedder, "zeta")] == ["keep.md"]
    assert await read_indexed_text(session, "gone.md", index_id=_GIT_INDEX, model_key="fake-v1") is None


async def test_deleted_content_keeps_its_cached_embedding(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    """The cache is content-addressed, so leaving the tip must not cost the vector."""
    first = commit(repo, {"keep.md": "alpha", "gone.md": "zeta zeta"})
    await run_sync(session, repo, first, embedder)
    await run_sync(session, repo, commit(repo, {"keep.md": "alpha"}), embedder)

    cached = await session.execute(
        select(func.count())
        .select_from(ContentEmbedding)
        .where(ContentEmbedding.content_sha == content_sha("zeta zeta"))
    )

    assert cached.scalar_one() > 0


async def test_restoring_deleted_content_costs_no_embedding(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    await run_sync(session, repo, commit(repo, {"keep.md": "alpha", "gone.md": "zeta zeta"}), embedder)
    await run_sync(session, repo, commit(repo, {"keep.md": "alpha"}), embedder)
    report = as_report(
        await run_sync(session, repo, commit(repo, {"keep.md": "alpha", "back.md": "zeta zeta"}), embedder)
    )

    assert report.blobs_embedded == 0
    assert next(hit.path for hit in await find(session, embedder, "zeta")) == "back.md"


async def test_resync_of_an_unchanged_tip_does_no_work(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    """The early-out is what lets a push trigger and a reconciling cron both fire freely."""
    head = commit(repo, {"a.md": "alpha", "b.md": "beta"})
    first = as_report(await run_sync(session, repo, head, embedder))
    second = await run_sync(session, repo, head, embedder)

    assert first.blobs_embedded == 2
    assert second == AlreadyCurrent(commit_sha=head)
    assert next(hit.path for hit in await find(session, embedder, "alpha")) == "a.md"


async def test_a_changed_model_resyncs_the_same_commit(session: AsyncSession, repo: pygit2.Repository) -> None:
    """Same tree, different regime: the stored vectors no longer answer for this content."""
    head = commit(repo, {"a.md": "alpha", "b.md": "beta"})
    await run_sync(session, repo, head, FakeEmbedder())

    successor = FakeEmbedder(model_key="fake-v2")
    report = as_report(await run_sync(session, repo, head, successor))

    assert report.blobs_embedded == 2
    assert next(hit.path for hit in await find(session, successor, "beta")) == "b.md"


async def test_a_failed_sync_leaves_the_previous_tip_searchable(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    first = commit(repo, {"a.md": "alpha"})
    await run_sync(session, repo, first, embedder)

    with pytest.raises(RuntimeError):
        await sync(
            session,
            repo,
            commit(repo, {"a.md": "alpha", "b.md": "beta"}),
            index_id=_GIT_INDEX,
            branch="main",
            embedder=ExplodingEmbedder(),
            now=_NOW,
        )
    await session.rollback()

    state = await current_git_state(session, _GIT_INDEX)
    assert state is not None
    assert state.commit_sha == first
    assert [hit.path for hit in await find(session, embedder, "alpha")] == ["a.md"]


async def test_binary_and_oversized_blobs_stay_out_of_the_index(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    index = pygit2.Index()
    index.add(pygit2.IndexEntry("a.md", repo.create_blob(b"alpha"), pygit2.enums.FileMode.BLOB))
    index.add(pygit2.IndexEntry("logo.png", repo.create_blob(b"\x89PNG\x00\xff\xfe"), pygit2.enums.FileMode.BLOB))
    head = str(repo.create_commit("refs/heads/main", _AUTHOR, _AUTHOR, "c", index.write_tree(repo), []))

    report = as_report(await run_sync(session, repo, head, embedder))

    assert (report.tip_files, report.skipped_binary) == (2, 1)
    assert all(hit.path != "logo.png" for hit in await find(session, embedder, "alpha"))


class FailsAfter:
    """Embeds `calls` batches and then dies — an endpoint that drops a call mid-sync."""

    def __init__(self, inner: FakeEmbedder, *, calls: int) -> None:
        self._inner = inner
        self._left = calls

    @property
    def model_key(self) -> str:
        return self._inner.model_key

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self._left == 0:
            raise RuntimeError("embedder died")
        self._left -= 1
        return await self._inner.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._inner.embed_query(text)


async def test_a_failed_sync_keeps_the_embeddings_it_already_paid_for(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    """Otherwise a first sync too big to finish in one go starts over forever."""
    head = commit(repo, {f"n{index}.md": f"alpha {index}" for index in range(EMBED_BATCH + 8)})

    with pytest.raises(RuntimeError):
        await sync(
            session, repo, head, index_id=_GIT_INDEX, branch="main", embedder=FailsAfter(embedder, calls=1), now=_NOW
        )
    await session.rollback()

    kept = await session.execute(select(func.count()).select_from(ContentEmbedding))
    assert kept.scalar_one() == EMBED_BATCH

    report = as_report(await run_sync(session, repo, head, embedder))

    assert (report.blobs_reused, report.blobs_embedded) == (EMBED_BATCH, 8)


async def test_a_failed_sync_publishes_no_tip(
    session: AsyncSession, repo: pygit2.Repository, embedder: FakeEmbedder
) -> None:
    """Committing chunks early must not make a half-indexed tree searchable."""
    head = commit(repo, {f"n{index}.md": f"alpha {index}" for index in range(EMBED_BATCH + 8)})

    with pytest.raises(RuntimeError):
        await sync(
            session, repo, head, index_id=_GIT_INDEX, branch="main", embedder=FailsAfter(embedder, calls=1), now=_NOW
        )
    await session.rollback()

    assert await current_git_state(session, _GIT_INDEX) is None
    assert await find(session, embedder, "alpha") == []


if __name__ == "__main__":
    pytest_bazel.main()
