"""Legacy raw-history setup for tests that exercise the retained app schema.

Not a runtime archive implementation. Service-backed reader tests pass their explicit
client through to the production reader; old raw-store tests retain their fixture reads.
"""

from collections.abc import Sequence
from datetime import UTC
from unittest.mock import AsyncMock
from uuid import UUID

from google.protobuf.json_format import MessageToDict, ParseDict
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agentplane.app.database_updates import Channel, notify
from agentplane.app.threads.events.debug import ArchivedObservation, ArchivedObservationEntry, ObservationPage
from agentplane.app.threads.events.event_log import (
    EventLogStore,
    EventReplicationError,
    FeedEnd,
    FeedError,
    FeedSnapshot,
    project_attached,
)
from agentplane.app.threads.model_activity import record_model_activity
from agentplane.app.threads.models import Event, EventLog, FeedState, ThreadHistorySummary
from agentplane.protocol import event_log_pb2
from agentplane.runner import protocol_pb2
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

    async def last_cursor(self, thread_id: UUID) -> int:
        async with self._sessions() as session:
            return (
                await session.scalar(
                    select(Event.cursor).where(Event.thread_id == thread_id).order_by(Event.cursor.desc()).limit(1)
                )
                or 0
            )

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

    async def resume_pending(self, thread_id: UUID) -> None:
        """A runner-confirmed restart supersedes a normal terminal feed, not a replay error.

        The ingester still owns the archived cursor and the next attached snapshot; this only
        prevents an SSE reader from mistaking the previous incarnation's end for the new one.
        """
        async with self._sessions.begin() as session:
            log = await session.get(EventLog, thread_id, with_for_update=True)
            state = (
                await session.get(ThreadHistorySummary, thread_id, with_for_update=True)
                if log is not None and log.raw_ingestion_fenced_at_cursor is not None
                else await session.get(FeedState, thread_id, with_for_update=True)
            )
            if state is not None and state.end == {}:
                state.end = None
                if isinstance(state, ThreadHistorySummary) and state.attached is not None:
                    state.resumed_after_cursor = ParseDict(state.attached, protocol_pb2.Attached()).last_cursor
                await notify(session, Channel.THREADS)

    async def feed_state(self, thread_id: UUID) -> FeedSnapshot | None:
        async with self._sessions() as session:
            log = await session.get(EventLog, thread_id)
            state = (
                await session.get(ThreadHistorySummary, thread_id)
                if log is not None and log.raw_ingestion_fenced_at_cursor is not None
                else await session.get(FeedState, thread_id)
            )
            if state is None or state.attached is None:
                return None
            end = None if state.end is None else FeedError(state.end["message"]) if state.end else FeedEnd()
            return FeedSnapshot(ParseDict(state.attached, protocol_pb2.Attached()), end)


async def append(
    session: AsyncSession, thread_id: UUID, entries: Sequence[event_log_pb2.EventEntry]
) -> list[event_log_pb2.EventEntry]:
    """Add the entries that extend the contiguous prefix and return them; a replayed entry must match."""
    last = await session.scalar(
        select(Event).where(Event.thread_id == thread_id).order_by(Event.cursor.desc()).limit(1)
    )
    cursor = last.cursor if last is not None else 0
    source_id = ParseDict(last.payload, event_log_pb2.EventEntry()).origin.source_id if last is not None else None
    payloads = dict(
        (
            await session.execute(
                select(Event.cursor, Event.payload).where(
                    Event.thread_id == thread_id,
                    Event.cursor.in_([entry.cursor for entry in entries if entry.cursor <= cursor]),
                )
            )
        )
        .tuples()
        .all()
    )
    inserted: list[event_log_pb2.EventEntry] = []
    for entry in entries:
        if not entry.cursor or not entry.origin.source_id or entry.origin.sequence != entry.cursor:
            raise EventReplicationError(f"invalid runner origin at cursor {entry.cursor}", cursor=entry.cursor)
        if source_id is not None and entry.origin.source_id != source_id:
            raise EventReplicationError(f"runner source changed at cursor {entry.cursor}", cursor=entry.cursor)
        payload = MessageToDict(entry)
        if entry.cursor in payloads:
            if payloads[entry.cursor] != payload:
                raise EventReplicationError(f"conflicting runner entry at cursor {entry.cursor}", cursor=entry.cursor)
            continue
        if entry.cursor != cursor + 1:
            raise EventReplicationError(
                f"expected runner cursor {cursor + 1}, received {entry.cursor}", cursor=entry.cursor
            )
        session.add(
            Event(
                thread_id=thread_id,
                cursor=entry.cursor,
                at=entry.event.at.ToDatetime(tzinfo=UTC),
                kind=entry.event.WhichOneof("observation") or "",
                payload=payload,
            )
        )
        payloads[entry.cursor] = payload
        inserted.append(entry)
        cursor = entry.cursor
        source_id = entry.origin.source_id
    await record_model_activity(session, thread_id, inserted)
    return inserted


async def advance_feed(session: AsyncSession, thread_id: UUID, inserted: Sequence[event_log_pb2.EventEntry]) -> None:
    """Carry the feed's attachment snapshot, and the log's model with it, over newly added entries."""
    state = await session.get(FeedState, thread_id)
    if state is not None:
        attached = ParseDict(state.attached, protocol_pb2.Attached())
        previous_model = attached.spec.model
        for entry in inserted:
            # An Attached snapshot describes the runner at its cursor. Replaying the
            # earlier log fills history, but must not rewind that snapshot's state.
            if entry.cursor <= attached.last_cursor:
                continue
            project_attached(attached, entry)
            if entry.event.HasField("harness_started"):
                state.end = None
        state.attached = MessageToDict(attached)
        if attached.spec.model != previous_model:
            await session.execute(update(EventLog).where(EventLog.id == thread_id).values(model=attached.spec.model))
        await session.flush()


async def set_attached(session: AsyncSession, thread_id: UUID, attached: protocol_pb2.Attached) -> None:
    state = await session.get(FeedState, thread_id)
    if state is not None and attached.last_cursor < ParseDict(state.attached, protocol_pb2.Attached()).last_cursor:
        raise ValueError("attachment snapshot is older than the committed feed state")
    values = {"attached": MessageToDict(attached), "end": None}
    await session.execute(
        insert(FeedState)
        .values(thread_id=thread_id, **values)
        .on_conflict_do_update(index_elements=[FeedState.thread_id], set_=values)
    )
    await session.execute(update(EventLog).where(EventLog.id == thread_id).values(model=attached.spec.model))


async def end_feed(session: AsyncSession, thread_id: UUID, error: str | None) -> None:
    state = await session.get(FeedState, thread_id)
    if state is None:
        raise ValueError("cannot end a feed before persisting its attachment")
    state.end = {} if error is None else {"message": error}
