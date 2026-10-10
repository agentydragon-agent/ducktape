"""Explicit retained database rows for compatibility tests, not a legacy writer."""

from collections.abc import Sequence
from datetime import UTC
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from google.protobuf.json_format import MessageToDict
from sqlalchemy import func, select

# gazelle:include_dep @pypi//protobuf
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from agentplane.app.threads.events.event_log import EventLogStore
from agentplane.app.threads.events.projection_lease import ProjectionLease
from agentplane.app.threads.ingestion import Ingestion
from agentplane.app.threads.model_activity import record_model_activity
from agentplane.app.threads.models import Event, EventLog, FeedState
from agentplane.app.threads.view.recording import record_thread_fold
from agentplane.protocol import event_log_pb2
from agentplane.runner import protocol_pb2
from agentplane.runner.harness import Harness
from agentplane.sandbox_service.client import SandboxServiceClient


async def seed_retained_session(
    engine: AsyncEngine, *, sandbox: str = "sb-1", locator: str = "s-retained", public_id: UUID | None = None
) -> UUID:
    thread = public_id if public_id is not None else uuid4()
    async with async_sessionmaker(engine).begin() as session:
        session.add(
            EventLog(
                id=thread,
                sandbox=sandbox,
                session_id=locator,
                harness=Harness.CLAUDE,
                model="test-model",
                cwd="/workspace",
            )
        )
    return thread


class RetainedEventLog(EventLogStore):
    """Minimal pre-handoff row setup and raw-cursor inspection for migration tests."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        history_reader: SandboxServiceClient | None = None,
        history_creator: SandboxServiceClient | None = None,
    ) -> None:
        self.engine = engine
        super().__init__(
            engine,
            history_reader=history_reader or AsyncMock(spec=SandboxServiceClient),
            history_creator=history_creator,
        )

    async def open(self, sandbox: str, session_id: str, spec: protocol_pb2.SessionSpec) -> UUID:
        if self._history_creator is not None:
            return await super().open(sandbox, session_id, spec)
        existing = await self.find(sandbox, session_id)
        if existing is not None:
            return existing
        thread = await seed_retained_session(self.engine, sandbox=sandbox, locator=session_id)
        async with self._sessions.begin() as session:
            row = await session.get(EventLog, thread)
            assert row is not None
            row.model, row.cwd = spec.model, spec.cwd
            row.harness = Harness(protocol_pb2.Harness.Name(spec.harness))
        return thread

    async def last_cursor(self, thread_id: UUID) -> int:
        async with self._sessions() as session:
            return await session.scalar(select(func.max(Event.cursor)).where(Event.thread_id == thread_id)) or 0


class RetainedRows(Ingestion):
    """Insert explicit historical rows, without replay/validation/reconnect behavior."""

    async def record(
        self, thread_id: UUID, entries: Sequence[event_log_pb2.EventEntry], *, lease: ProjectionLease
    ) -> None:
        async with self._sessions.begin() as session:
            session.add_all(
                [
                    Event(
                        thread_id=thread_id,
                        cursor=e.cursor,
                        at=e.event.at.ToDatetime(tzinfo=UTC),
                        kind=e.event.WhichOneof("observation") or "",
                        payload=MessageToDict(e),
                    )
                    for e in entries
                ]
            )
            if entries:
                await record_thread_fold(session, thread_id, entries[0].origin.source_id, entries)
                await record_model_activity(session, thread_id, entries)

    async def set_attached(self, thread_id: UUID, attached: protocol_pb2.Attached, *, lease: ProjectionLease) -> None:
        async with self._sessions.begin() as session:
            session.add(FeedState(thread_id=thread_id, attached=MessageToDict(attached)))

    async def end_feed(self, thread_id: UUID, *, lease: ProjectionLease, error: str | None) -> None:
        async with self._sessions.begin() as session:
            state = await session.get(FeedState, thread_id)
            assert state is not None
            state.end = {} if error is None else {"message": error}
