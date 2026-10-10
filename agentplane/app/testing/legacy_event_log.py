"""Legacy raw-history setup for tests that exercise the retained app schema.

Not a runtime archive implementation. Service-backed reader tests pass their explicit
client through to the production reader; old raw-store tests retain their fixture reads.
"""

from unittest.mock import AsyncMock
from uuid import UUID

from google.protobuf.json_format import ParseDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from agentplane.app.threads.events.debug import ArchivedObservation, ArchivedObservationEntry, ObservationPage
from agentplane.app.threads.events.event_log import EventLogStore
from agentplane.app.threads.models import Event
from agentplane.protocol import event_log_pb2
from agentplane.sandbox_service.client import SandboxServiceClient

# gazelle:include_dep @pypi//protobuf


class LegacyEventLogStore(EventLogStore):
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        history_reader: SandboxServiceClient | None = None,
        history_creator: SandboxServiceClient | None = None,
    ) -> None:
        super().__init__(
            engine,
            history_reader=history_reader or AsyncMock(spec=SandboxServiceClient),
            history_creator=history_creator,
        )
        self._read_legacy = history_reader is None

    async def read_watermark(self, thread_id: UUID) -> int:
        if self._read_legacy:
            return await self.last_cursor(thread_id)
        return await super().read_watermark(thread_id)

    async def events(self, thread_id: UUID, *, after_cursor: int = 0, limit: int) -> list[event_log_pb2.EventEntry]:
        """Up to `limit` entries after the cursor, in cursor order; a reader pages until a short page."""
        if not self._read_legacy:
            return await super().events(thread_id, after_cursor=after_cursor, limit=limit)
        async with self._sessions() as session:
            payloads = await session.scalars(
                select(Event.payload)
                .where(Event.thread_id == thread_id, Event.cursor > after_cursor)
                .order_by(Event.cursor)
                .limit(limit)
            )
            return [ParseDict(payload, event_log_pb2.EventEntry()) for payload in payloads]

    async def observations(
        self, thread_id: UUID, *, before_cursor: int | None = None, after_cursor: int | None = None, limit: int = 30
    ) -> ObservationPage:
        """Seek directly into the immutable archive; never fold or load intervening history."""
        if (
            not 1 <= limit <= 200
            or (before_cursor is not None and before_cursor < 0)
            or (after_cursor is not None and after_cursor < 0)
            or (before_cursor is not None and after_cursor is not None)
        ):
            raise ValueError("invalid chronological observation page bounds")
        if not self._read_legacy:
            return await super().observations(
                thread_id, before_cursor=before_cursor, after_cursor=after_cursor, limit=limit
            )
        async with self._sessions() as session:
            query = select(Event.cursor, Event.kind).where(Event.thread_id == thread_id)
            if after_cursor is not None:
                query = query.where(Event.cursor > after_cursor).order_by(Event.cursor)
            else:
                if before_cursor is not None:
                    query = query.where(Event.cursor < before_cursor)
                query = query.order_by(Event.cursor.desc())
            rows = list(await session.execute(query.limit(limit)))
            if after_cursor is None:
                rows.reverse()
            if not rows:
                return ObservationPage(observations=[], next_before_cursor=None, next_after_cursor=None)
            has_older = await session.scalar(
                select(select(Event.cursor).where(Event.thread_id == thread_id, Event.cursor < rows[0].cursor).exists())
            )
            has_newer = await session.scalar(
                select(
                    select(Event.cursor).where(Event.thread_id == thread_id, Event.cursor > rows[-1].cursor).exists()
                )
            )
            return ObservationPage(
                observations=[ArchivedObservation(cursor=str(row.cursor), kind=row.kind) for row in rows],
                next_before_cursor=str(rows[0].cursor) if has_older else None,
                next_after_cursor=str(rows[-1].cursor) if has_newer else None,
            )

    async def observation_entry(self, thread_id: UUID, cursor: int) -> ArchivedObservationEntry | None:
        """One raw archive entry, read only when a reader expands that observation."""
        if not self._read_legacy:
            return await super().observation_entry(thread_id, cursor)
        async with self._sessions() as session:
            payload = await session.scalar(
                select(Event.payload).where(Event.thread_id == thread_id, Event.cursor == cursor)
            )
            return None if payload is None else ArchivedObservationEntry(cursor=str(cursor), entry=payload)
