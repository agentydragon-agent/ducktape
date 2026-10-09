"""Bounded service-history projection primitive; deliberately not wired into app startup.

The rollout must fence runner-backed ingestion before scheduling this worker. Reuse the
app lease and existing UI checkpoint; never acquire runner storage or copy raw Event rows.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from agentplane.app.database_updates import Channel, notify
from agentplane.app.threads.events import ingestion_lease
from agentplane.app.threads.events.event_log import EventReplicationError
from agentplane.app.threads.events.ingestion_lease import IngestionLease
from agentplane.app.threads.models import ThreadCheckpoint
from agentplane.app.threads.view.recording import record_thread_fold
from agentplane.sandbox_service.client import SandboxServiceClient

# gazelle:include_dep @pypi//protobuf
# gazelle:include_dep //agentplane/sandbox_service:protocol_pb2


@dataclass(frozen=True)
class ProjectionProgress:
    through_cursor: int
    service_cursor: int


class HistoryProjector:
    def __init__(self, engine: AsyncEngine, reader: SandboxServiceClient) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._reader = reader

    async def project_batch(self, thread_id: UUID, *, lease: IngestionLease) -> ProjectionProgress:
        """Resume from the UI checkpoint; a failed fold leaves that checkpoint unchanged."""
        async with self._sessions() as session:
            after = (
                await session.scalar(
                    select(ThreadCheckpoint.through_cursor).where(ThreadCheckpoint.thread_id == thread_id)
                )
                or 0
            )
        page = await self._reader.read_session_events(str(thread_id), after_cursor=after, limit=128)
        if page.last_cursor < after:
            raise ConnectionError("Sandbox Service has not covered the projection checkpoint")
        if len(page.entries) > 128 or any(
            entry.cursor != after + index + 1
            or entry.cursor > page.last_cursor
            or entry.origin.sequence != entry.cursor
            or not entry.origin.source_id
            for index, entry in enumerate(page.entries)
        ):
            raise EventReplicationError("invalid service history projection page")
        if not page.entries and after < page.last_cursor:
            raise EventReplicationError("service omitted entries from its committed prefix")
        async with self._sessions.begin() as session:
            # Serializes with other writes under this sandbox lease, including a
            # delayed batch from an old owner. Do not hold the fence over the RPC.
            await ingestion_lease.fence(session, lease, thread_id)
            current = (
                await session.scalar(
                    select(ThreadCheckpoint.through_cursor).where(ThreadCheckpoint.thread_id == thread_id)
                )
                or 0
            )
            if current != after:
                raise ConnectionError("projection checkpoint advanced during fetch; retry from checkpoint")
            if not page.entries:
                return ProjectionProgress(after, page.last_cursor)
            source_id = page.entries[0].origin.source_id
            if any(entry.origin.source_id != source_id for entry in page.entries):
                raise EventReplicationError("mixed source identities in projection page")
            await record_thread_fold(session, thread_id, source_id, page.entries)
            await notify(session, Channel.THREADS)
        return ProjectionProgress(page.entries[-1].cursor, page.last_cursor)
