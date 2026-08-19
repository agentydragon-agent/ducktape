"""Contract tests for the configured-index ``haku_index`` MCP surface."""

from __future__ import annotations

import datetime
from uuid import UUID

import pytest_bazel
from fastmcp import Client

from haku.console.tools.recall_index import (
    HAKU_INDEX_SERVER_ID,
    ChatIndexStatus,
    ChatSource,
    GitIndexStatus,
    GitSource,
    IndexStatus,
    SearchHit,
    SearchResults,
    build_mcp,
)

NOW = datetime.datetime(2026, 8, 14, 9, 0, tzinfo=datetime.UTC)
SESSION = UUID("11111111-1111-1111-1111-111111111111")
MESSAGES = [UUID("22222222-2222-2222-2222-222222222222"), UUID("33333333-3333-3333-3333-333333333333")]


def _git_hit(score: float) -> SearchHit:
    return SearchHit(
        score=score,
        content="how to file an intake item",
        source=GitSource(
            index_id="haku-state",
            path="notes/intake.md",
            commit_sha="deadbeef",
            blob_sha="cafe1234",
            byte_start=0,
            byte_end=40,
        ),
    )


def _chat_hit(score: float) -> SearchHit:
    return SearchHit(
        score=score,
        content="user: what about the egress fence",
        source=ChatSource(
            index_id="haku-conversations",
            session_id=SESSION,
            room_id="!room:allegedly.works",
            message_ids=MESSAGES,
            first_message_at=NOW,
            last_message_at=NOW,
        ),
    )


class _Searcher:
    def __init__(self, *hits: SearchHit, behind: bool = False) -> None:
        self.hits = list(hits)
        self.behind = behind
        self.queries: list[dict] = []

    async def search(
        self,
        query: str,
        *,
        index_ids: tuple[str, ...] | None,
        limit: int,
        path_prefix: str | None,
        session_id: UUID | None,
    ) -> SearchResults:
        self.queries.append(
            {
                "query": query,
                "index_ids": index_ids,
                "limit": limit,
                "path_prefix": path_prefix,
                "session_id": session_id,
            }
        )
        return SearchResults(hits=self.hits, index=await self.status() if self.behind else None)

    async def status(self) -> IndexStatus:
        return IndexStatus(
            indexes=[
                GitIndexStatus(
                    index_id="haku-state",
                    indexed_commit="abc123",
                    remote_commit="abc123",
                    remote_seen_at=NOW,
                    branch="main",
                    indexed_at=NOW,
                    files=12,
                    chunks=40,
                    embedded_chunks=40,
                    pending_chunks=0,
                    superseded_chunks=0,
                ),
                ChatIndexStatus(
                    index_id="haku-conversations",
                    sessions=3,
                    chunks=9,
                    embedded_chunks=8,
                    pending_chunks=1,
                    stale_sessions=1,
                    unindexed_messages=4,
                    lag_seconds=120.0,
                    last_indexed_at=NOW,
                    superseded_chunks=0,
                ),
            ]
        )


async def test_a_git_hit_carries_the_index_and_exact_file_pointer() -> None:
    async with Client(build_mcp(_Searcher(_git_hit(0.9)))) as client:
        (hit,) = (await client.call_tool("search", {"query": "intake"})).data.hits
    assert hit.content == "how to file an intake item"
    assert (hit.source["index_id"], hit.source["path"], hit.source["commit_sha"], hit.source["blob_sha"]) == (
        "haku-state",
        "notes/intake.md",
        "deadbeef",
        "cafe1234",
    )


async def test_a_chat_hit_carries_its_index_session_room_and_messages() -> None:
    async with Client(build_mcp(_Searcher(_chat_hit(0.8)))) as client:
        (hit,) = (await client.call_tool("search", {"query": "egress fence"})).data.hits
    assert (hit.source["index_id"], hit.source["session_id"], hit.source["room_id"]) == (
        "haku-conversations",
        str(SESSION),
        "!room:allegedly.works",
    )
    assert hit.source["message_ids"] == [str(message_id) for message_id in MESSAGES]


async def test_content_is_included_by_default_or_explicit_request_and_omitted_on_request() -> None:
    async with Client(build_mcp(_Searcher(_git_hit(0.9)))) as client:
        default = await client.call_tool("search", {"query": "intake"})
        explicit = await client.call_tool("search", {"query": "intake", "include_content": True})
        pointer_only = await client.call_tool("search", {"query": "intake", "include_content": False})
    assert default.structured_content["hits"][0]["content"] == "how to file an intake item"
    assert explicit.structured_content["hits"][0]["content"] == "how to file an intake item"
    assert "content" not in pointer_only.structured_content["hits"][0]


async def test_omitted_index_ids_means_the_configured_set_not_special_source_names() -> None:
    searcher = _Searcher()
    async with Client(build_mcp(searcher)) as client:
        await client.call_tool("search", {"query": "intake"})
    assert searcher.queries[-1]["index_ids"] is None


async def test_selected_index_ids_and_session_filter_reach_the_searcher() -> None:
    searcher = _Searcher()
    async with Client(build_mcp(searcher)) as client:
        await client.call_tool(
            "search", {"query": "intake", "index_ids": ["haku-conversations"], "session_id": str(SESSION)}
        )
    query = searcher.queries[-1]
    assert (query["index_ids"], query["session_id"]) == (("haku-conversations",), SESSION)


async def test_a_behind_index_rides_along_with_status() -> None:
    async with Client(build_mcp(_Searcher(behind=True))) as client:
        results = (await client.call_tool("search", {"query": "intake"})).data
    assert results.index is not None
    assert results.index.indexes[1]["unindexed_messages"] == 4


async def test_status_reports_every_configured_index() -> None:
    async with Client(build_mcp(_Searcher())) as client:
        status = (await client.call_tool("index_status", {})).data
    assert [(item["index_id"], item["index_type"]) for item in status.indexes] == [
        ("haku-state", "git"),
        ("haku-conversations", "chat"),
    ]


def test_the_server_is_named_for_its_id() -> None:
    assert build_mcp(_Searcher()).name == HAKU_INDEX_SERVER_ID


if __name__ == "__main__":
    pytest_bazel.main()
