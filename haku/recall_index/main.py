"""CLI for named recall indexes: build one, query one, and report one.

Point it at a clone of haku-state or at a copy of the console's database and it builds and
searches the index against any Postgres with pgvector, including a throwaway one.

Every command takes an explicit index id rather than defaulting: a query that silently searched
the wrong one would look like a retrieval quality problem.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from haku.recall_index.chat_sync import sync_chat
from haku.recall_index.chunking import DEFAULT_CHUNK_BUDGET, ChunkBudget
from haku.recall_index.embedding_sync import embed_pending
from haku.recall_index.git_tree import fetch_branch, open_mirror
from haku.recall_index.openai_embedder import OpenAIEmbedder
from haku.recall_index.query import query_chat, query_git
from haku.recall_index.schema import IndexType
from haku.recall_index.store import chat_index_summary, current_git_state, ensure_schema, register_index
from haku.recall_index.sync import AlreadyCurrent, sync

app = typer.Typer(help=__doc__)

DatabaseUrl = Annotated[str, typer.Option(envvar="HAKU_STATE_INDEX_DATABASE_URL")]


def _budget() -> ChunkBudget:
    """How big a chunk gets, from the environment.

    Read here rather than passed per command because it has to be the same for indexing and for
    querying: it is part of the cache key, so a query under a different budget searches a regime
    nothing was written under and finds nothing at all.
    """
    return ChunkBudget(
        target_bytes=int(os.environ.get("HAKU_STATE_INDEX_CHUNK_TARGET_BYTES", DEFAULT_CHUNK_BUDGET.target_bytes)),
        max_bytes=int(os.environ.get("HAKU_STATE_INDEX_CHUNK_MAX_BYTES", DEFAULT_CHUNK_BUDGET.max_bytes)),
        overlap_codepoints=int(
            os.environ.get("HAKU_STATE_INDEX_CHUNK_OVERLAP_CODEPOINTS", DEFAULT_CHUNK_BUDGET.overlap_codepoints)
        ),
    )


def _embedder() -> OpenAIEmbedder:
    """The same embedder the console uses, so an evaluation here measures what ships.

    Point it at the cluster's Ollama (port-forward `ollama.ollama:11434`) or at one running
    locally; the model must be the one actually served, since the client fails closed on a
    mismatch rather than writing a second vector space into the corpus.
    """
    return OpenAIEmbedder(
        AsyncOpenAI(
            base_url=os.environ.get("HAKU_STATE_INDEX_EMBEDDER_URL", "http://localhost:11434/v1"), api_key="not-used"
        ),
        model=os.environ.get("HAKU_STATE_INDEX_EMBEDDER_MODEL", "qwen3-embedding:4b"),
        query_instruction=os.environ.get("HAKU_STATE_INDEX_EMBEDDER_QUERY_INSTRUCTION", ""),
    )


async def _index_git(
    database_url: str,
    index_id: str,
    repo_url: str,
    branch: str,
    mirror: Path,
    username: str | None,
    password: str | None,
) -> None:
    engine = create_async_engine(database_url)
    try:
        await ensure_schema(engine)
        repository = open_mirror(mirror, repo_url, username=username, password=password)
        commit_sha = fetch_branch(repository, branch, username=username, password=password)
        async with async_sessionmaker(engine)() as session:
            await register_index(session, index_id, index_type=IndexType.GIT)
            outcome = await sync(
                session,
                repository,
                commit_sha,
                index_id=index_id,
                branch=branch,
                now=datetime.datetime.now(datetime.UTC),
                budget=_budget(),
            )
            await session.commit()
    finally:
        await engine.dispose()
    if isinstance(outcome, AlreadyCurrent):
        typer.echo(f"{outcome.commit_sha[:12]} already indexed — nothing to do")
        return
    typer.echo(
        f"{outcome.commit_sha[:12]} {outcome.tip_files} files, {outcome.chunks_written} chunks written "
        f"({outcome.contents_materialized} content values materialized, "
        f"{outcome.skipped_binary} binary, {outcome.skipped_large} oversized)"
    )


@app.command("index-git")
def index_git(
    index_id: Annotated[str, typer.Argument()],
    repo_url: Annotated[str, typer.Argument()],
    database_url: DatabaseUrl,
    branch: str = "main",
    mirror: Path = Path("/var/lib/haku-recall-index/mirror.git"),
    username: Annotated[str | None, typer.Option(envvar="HAKU_STATE_INDEX_GIT_USERNAME")] = None,
    password: Annotated[str | None, typer.Option(envvar="HAKU_STATE_INDEX_GIT_PASSWORD")] = None,
) -> None:
    """Fetch `branch` into the mirror and materialize its source chunks."""
    asyncio.run(_index_git(database_url, index_id, repo_url, branch, mirror, username, password))


async def _index_chat(database_url: str, index_id: str) -> None:
    engine = create_async_engine(database_url)
    try:
        await ensure_schema(engine)
        async with async_sessionmaker(engine)() as session:
            await register_index(session, index_id, index_type=IndexType.CHAT)
            report = await sync_chat(
                session, index_id=index_id, now=datetime.datetime.now(datetime.UTC), budget=_budget()
            )
            await session.commit()
    finally:
        await engine.dispose()
    typer.echo(
        f"{report.sessions_indexed} sessions indexed, {report.sessions_unchanged} unchanged, "
        f"{report.sessions_forgotten} forgotten; {report.windows_written} windows written "
        f"({report.contents_materialized} content values materialized)"
    )


@app.command("index-chat")
def index_chat(index_id: Annotated[str, typer.Argument()], database_url: DatabaseUrl) -> None:
    """Materialize every chat session that has changed since it was last indexed.

    The database must be the console's own: the corpus is its `conversation_item` table.
    """
    asyncio.run(_index_chat(database_url, index_id))


async def _embed(database_url: str) -> None:
    """Drain the global content queue for the configured embedding model."""
    engine = create_async_engine(database_url)
    total = 0
    try:
        async with async_sessionmaker(engine)() as session:
            while (report := await embed_pending(session, embedder=_embedder())).contents_embedded:
                total += report.contents_embedded
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()
    typer.echo(f"{total} content values embedded")


@app.command()
def embed(database_url: DatabaseUrl) -> None:
    """Embed source-materialized content that lacks a vector for the configured model."""
    asyncio.run(_embed(database_url))


async def _query_git(database_url: str, index_id: str, query: str, limit: int, path_prefix: str | None) -> None:
    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            hits = await query_git(
                session, _embedder(), query, index_id=index_id, limit=limit, path_prefix=path_prefix, budget=_budget()
            )
    finally:
        await engine.dispose()
    for hit in hits:
        preview = " ".join(hit.text.split())[:160]
        typer.echo(f"{hit.score:.3f} {hit.path} [{hit.byte_start}:{hit.byte_end}] {preview}")


@app.command("query-git")
def query_git_command(
    index_id: Annotated[str, typer.Argument()],
    text: Annotated[str, typer.Argument()],
    database_url: DatabaseUrl,
    limit: int = 10,
    path_prefix: str | None = None,
) -> None:
    """Search the indexed git tip."""
    asyncio.run(_query_git(database_url, index_id, text, limit, path_prefix))


async def _query_chat(database_url: str, index_id: str, query: str, limit: int, session_id: UUID | None) -> None:
    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            hits = await query_chat(
                session, _embedder(), query, index_id=index_id, limit=limit, session_id=session_id, budget=_budget()
            )
    finally:
        await engine.dispose()
    for hit in hits:
        preview = " ".join(hit.text.split())[:160]
        typer.echo(
            f"{hit.score:.3f} {hit.session_id}#{hit.window_no} "
            f"{hit.first_message_at:%Y-%m-%d %H:%M} +{len(hit.message_ids)} msg {preview}"
        )


@app.command("query-chat")
def query_chat_command(
    index_id: Annotated[str, typer.Argument()],
    text: Annotated[str, typer.Argument()],
    database_url: DatabaseUrl,
    limit: int = 10,
    session_id: Annotated[UUID | None, typer.Option()] = None,
) -> None:
    """Search the indexed chat sessions."""
    asyncio.run(_query_chat(database_url, index_id, text, limit, session_id))


async def _status(database_url: str, index_id: str, index_type: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            git = await current_git_state(session, index_id) if index_type == "git" else None
            chat = await chat_index_summary(session, index_id) if index_type == "chat" else None
    finally:
        await engine.dispose()
    if index_type == "git":
        if git is None:
            typer.echo("git: empty — no sweep has looked at the remote yet")
        elif git.commit_sha is None:
            typer.echo(
                f"git: {git.branch}@{git.remote_commit[:12] if git.remote_commit else '?'} seen, nothing indexed yet"
            )
        else:
            typer.echo(
                f"git: {git.branch}@{git.commit_sha[:12]} synced {git.synced_at.isoformat() if git.synced_at else '?'} "
                f"(chunker {git.chunker_key})"
            )
        return

    if chat is None or chat.last_indexed_at is None:
        typer.echo("chat: empty — nothing synced yet")
        return
    typer.echo(
        f"chat: {chat.sessions} sessions, {chat.chunks} windows, last indexed {chat.last_indexed_at.isoformat()}"
    )


@app.command()
def status(
    index_id: Annotated[str, typer.Argument()], index_type: Annotated[str, typer.Argument()], database_url: DatabaseUrl
) -> None:
    """What one named index's searchable set currently holds."""
    if index_type not in {"git", "chat"}:
        raise typer.BadParameter("index_type must be 'git' or 'chat'")
    asyncio.run(_status(database_url, index_id, index_type))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app()


if __name__ == "__main__":
    main()
