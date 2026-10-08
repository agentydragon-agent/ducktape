"""Transactionally append and replay a runner's contiguous Event prefix."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from agentplane.protocol import event_log_pb2
from agentplane.sandbox_service.archive.db import ArchivedEvent, SessionArchive


class ArchiveConflict(ValueError):
    """An entry skips or disagrees with the already archived runner prefix."""


class ArchiveNotFound(LookupError):
    pass


class Store:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def open(
        self, session_id: UUID, *, sandbox_namespace: str, sandbox_name: str,
        sandbox_uid: UUID | None, runner_session_id: str,
    ) -> None:
        """Register a durable ID and its immutable physical locator, including legacy IDs.

        The ID belongs to the Session (and remains usable after the Sandbox is deleted).
        Re-opening the same ID with another runner is an error, not a history overwrite.
        """
        from sqlalchemy.dialects.postgresql import insert

        async with self._sessions.begin() as session:
            await session.execute(
                insert(SessionArchive).values(
                    id=session_id, sandbox_namespace=sandbox_namespace, sandbox_name=sandbox_name,
                    sandbox_uid=sandbox_uid, runner_session_id=runner_session_id,
                    source_id=None, last_cursor=0,
                ).on_conflict_do_nothing(index_elements=[SessionArchive.id])
            )
            row = await session.get(SessionArchive, session_id)
            assert row is not None
            if (row.sandbox_namespace, row.sandbox_name, row.sandbox_uid, row.runner_session_id) != (
                sandbox_namespace, sandbox_name, sandbox_uid, runner_session_id,
            ):
                raise ArchiveConflict(f"session {session_id} has a different runner locator")

    async def append(self, session_id: UUID, entries: Sequence[event_log_pb2.EventEntry]) -> int:
        """Replay exact duplicates or extend the prefix; serialize concurrent writers by Session ID.

        Validation and the new checkpoint commit together. On any error the entire batch rolls
        back. An empty batch is a checkpoint read, not an inferred runner high-water mark.
        """
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(SessionArchive).where(SessionArchive.id == session_id).with_for_update()
            )
            if row is None:
                raise ArchiveNotFound(session_id)
            for entry in entries:
                cursor = entry.cursor
                if cursor == 0 or not entry.origin.source_id or entry.origin.sequence != cursor:
                    raise ArchiveConflict(f"invalid runner origin at {cursor}")
                if row.source_id is not None and row.source_id != entry.origin.source_id:
                    raise ArchiveConflict(f"source changed at {cursor}")
                payload = entry.SerializeToString(deterministic=True)
                if cursor <= row.last_cursor:
                    existing = await session.get(ArchivedEvent, (session_id, cursor))
                    if existing is None or existing.payload != payload:
                        raise ArchiveConflict(f"conflicting entry at {cursor}")
                    continue
                if cursor != row.last_cursor + 1:
                    raise ArchiveConflict(f"expected {row.last_cursor + 1}, received {cursor}")
                session.add(ArchivedEvent(session_id=session_id, cursor=cursor, payload=payload))
                row.source_id = entry.origin.source_id
                row.last_cursor = cursor
            return row.last_cursor

    async def read(
        self, session_id: UUID, *, after_cursor: int = 0, limit: int = 128,
    ) -> tuple[int, list[event_log_pb2.EventEntry]]:
        """Internal replay only; never expose this as an unscoped workload read API."""
        if after_cursor < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid archive page")
        async with self._sessions() as session:
            archive = await session.get(SessionArchive, session_id)
            if archive is None:
                raise ArchiveNotFound(session_id)
            if after_cursor > archive.last_cursor:
                raise ValueError("cursor beyond archived prefix")
            rows = await session.scalars(
                select(ArchivedEvent).where(
                    ArchivedEvent.session_id == session_id, ArchivedEvent.cursor > after_cursor,
                ).order_by(ArchivedEvent.cursor).limit(limit)
            )
            return archive.last_cursor, [event_log_pb2.EventEntry.FromString(row.payload) for row in rows]
