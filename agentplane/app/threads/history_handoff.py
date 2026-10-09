"""Explicit per-Thread writer fence; not exposed by RPC or invoked at app startup."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from agentplane.app.database_updates import Channel, notify
from agentplane.app.threads.events.event_log import ThreadNotFoundError
from agentplane.app.threads.models import Event, EventLog


async def fence_raw_ingestion(engine: AsyncEngine, thread_id: UUID) -> int:
    """Persist the final raw cursor after draining in-flight legacy writer transactions.

    Database triggers reject subsequent Event/feed-state writes, including from old app
    replicas after lease expiry/reacquisition. This is intentionally one-way: clearing the
    fence would require reconciling history written after handoff, not a flag rollback.
    Caller must establish service readiness before requesting this mutating operation.
    """
    async with async_sessionmaker(engine).begin() as session:
        log = await session.scalar(select(EventLog).where(EventLog.id == thread_id).with_for_update())
        if log is None:
            raise ThreadNotFoundError(thread_id)
        if log.raw_ingestion_fenced_at_cursor is not None:
            return log.raw_ingestion_fenced_at_cursor
        cursor = (
            await session.scalar(
                select(Event.cursor).where(Event.thread_id == thread_id).order_by(Event.cursor.desc()).limit(1)
            )
            or 0
        )
        log.raw_ingestion_fenced_at_cursor = cursor
        await notify(session, Channel.THREADS)
        return cursor
