"""haku-console's in-process ``haku_index`` MCP server — configured semantic recall.

Configured logical indexes are the retrieval and future authorization boundary. A search defaults
to every configured index, never to a conventionally named source; callers may narrow it with
``index_ids``. The current deployment config supplies Git indexes for haku-state and public
Ducktape, plus a chat index over the console's completed messages.

Search returns indexed chunk content by default, plus source pointers. Callers that only need
provenance can suppress the content payload. A Git hit names its indexed commit and blob; a chat
hit names its session and messages.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastmcp import FastMCP
from pydantic import BaseModel, Field

HAKU_INDEX_SERVER_ID = "haku_index"
MAX_RESULTS = 25
DEFAULT_RESULTS = 8


class GitSource(BaseModel):
    """Where a hit sits in a configured Git index, at its indexed commit."""

    kind: Literal["git"] = "git"
    index_id: str
    path: str = Field(description="Path at `commit_sha`.")
    commit_sha: str = Field(description="The indexed Git commit containing this path.")
    blob_sha: str = Field(description="Git blob sha holding the exact indexed bytes.")
    byte_start: int = Field(description="Start of the matching span, in bytes into the blob.")
    byte_end: int


class ChatSource(BaseModel):
    """Where a hit sits in a configured console-chat index."""

    kind: Literal["chat"] = "chat"
    index_id: str
    session_id: UUID = Field(description="Pass to `haku_conversations` to read the session around this.")
    room_id: str | None = Field(description="The Matrix room this session served, if it served one.")
    message_ids: list[UUID] = Field(description="The messages this window holds, in order.")
    first_message_at: datetime.datetime
    last_message_at: datetime.datetime


class SearchHit(BaseModel):
    """One match and a source-specific pointer to its authoritative bytes."""

    score: float
    source: GitSource | ChatSource = Field(discriminator="kind")
    content: str | None = Field(
        default=None,
        description="The matching indexed chunk text, omitted when `include_content` is false.",
        exclude_if=lambda value: value is None,
    )


class GitIndexStatus(BaseModel):
    index_type: Literal["git"] = "git"
    index_id: str
    indexed_commit: str | None = None
    remote_commit: str | None = None
    remote_seen_at: datetime.datetime | None = None
    branch: str | None = None
    indexed_at: datetime.datetime | None = None
    files: int = 0
    chunks: int = 0
    embedded_chunks: int = 0
    pending_chunks: int = 0
    superseded_chunks: int = 0


class ChatIndexStatus(BaseModel):
    index_type: Literal["chat"] = "chat"
    index_id: str
    sessions: int
    chunks: int
    embedded_chunks: int
    pending_chunks: int
    stale_sessions: int
    unindexed_messages: int
    lag_seconds: float | None
    last_indexed_at: datetime.datetime | None
    superseded_chunks: int


class IndexStatus(BaseModel):
    """Status for every configured logical index, not a fixed pair of special sources."""

    indexes: list[Annotated[GitIndexStatus | ChatIndexStatus, Field(discriminator="index_type")]]


class SearchResults(BaseModel):
    """Hits plus status only when a selected configured index was behind."""

    hits: list[SearchHit]
    index: IndexStatus | None = None

    def without_content(self) -> SearchResults:
        """Drop chunk text while retaining ranking, provenance, and stale-index status."""
        return SearchResults(
            hits=[SearchHit(score=hit.score, source=hit.source) for hit in self.hits], index=self.index
        )


class IndexSearcher(Protocol):
    async def search(
        self,
        query: str,
        *,
        index_ids: tuple[str, ...] | None,
        limit: int,
        path_prefix: str | None,
        session_id: UUID | None,
    ) -> SearchResults: ...

    async def status(self) -> IndexStatus: ...


def build_mcp(searcher: IndexSearcher) -> FastMCP:
    mcp: FastMCP = FastMCP(name=HAKU_INDEX_SERVER_ID, instructions="Semantic recall over configured logical indexes.")

    @mcp.tool
    async def search(
        query: Annotated[str, Field(description="Natural language. This is semantic search, not grep.")],
        index_ids: Annotated[
            list[str] | None,
            Field(
                default=None, description="Configured logical indexes to search. Omit to search every configured index."
            ),
        ] = None,
        limit: Annotated[int, Field(default=DEFAULT_RESULTS, ge=1, le=MAX_RESULTS)] = DEFAULT_RESULTS,
        path_prefix: Annotated[
            str | None, Field(default=None, description="Restrict matching paths in selected Git indexes.")
        ] = None,
        session_id: Annotated[
            UUID | None, Field(default=None, description="Restrict matching windows in selected chat indexes.")
        ] = None,
        include_content: Annotated[
            bool,
            Field(
                default=True,
                description="Include matching indexed chunk text. Defaults to true; set false for provenance only.",
            ),
        ] = True,
    ) -> SearchResults:
        """Search configured indexes for recall.

        **Recall step, not an optional one.** Run this before answering about prior work,
        decisions, dates, people, preferences, commitments, or anything the operator asked for
        earlier. Results compete in one ranking across the selected indexes.
        """
        results = await searcher.search(
            query,
            index_ids=None if index_ids is None else tuple(index_ids),
            limit=limit,
            path_prefix=path_prefix,
            session_id=session_id,
        )
        return results if include_content else results.without_content()

    @mcp.tool
    async def index_status() -> IndexStatus:
        """How current every configured logical index is."""
        return await searcher.status()

    return mcp
