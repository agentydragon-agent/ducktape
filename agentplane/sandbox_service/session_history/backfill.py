"""One-shot, replayable app Event-log -> Sandbox Service Session history import.

Run while app remains the source of truth. This is deliberately NOT an Alembic
migration or an automatic retry loop: a mismatch aborts the Job for inspection.
Re-run after live app ingestion catches up, before enabling shadow ingestion.
"""

import asyncio
import json
import logging
from time import monotonic
from uuid import UUID

from google.protobuf.json_format import ParseDict, ParseError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from agentplane.protocol import event_log_pb2
from agentplane.sandbox_service.session_history.db import SessionHistory
from agentplane.sandbox_service.session_history.store import HistoryConflictError, Store

# SQLAlchemy loads this dialect by URL. Generated EventEntry stubs also need protobuf.
# gazelle:include_dep @pypi//asyncpg
# gazelle:include_dep @pypi//protobuf

logger = logging.getLogger(__name__)
PAGE_SIZE = 128
PROGRESS_INTERVAL = 8192
DATA_CONFLICT_EXIT_CODE = 2


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTPLANE_HISTORY_BACKFILL_")
    app_database_url: str
    sandbox_service_database_url: str
    sandbox_namespace: str


async def import_log(
    source: AsyncEngine, destination: AsyncEngine, *, namespace: str, log_id: UUID, sandbox: str, runner_id: str
) -> int:
    """Copy a bounded source prefix per call, checking the persisted checkpoint and first Event.

    For a service-owned ID the app stores the public UUID in event_log.session_id,
    not the private r-UUID runner locator. Existing reservations preserve that locator.
    A legacy log without a confirmed Sandbox incarnation retains a NULL UID and
    MUST NOT be polled by the shadow ingester until its identity is established.
    """
    store = Store(destination)
    async with async_sessionmaker(destination)() as session:
        existing = await session.get(SessionHistory, log_id)
    if existing is None:
        await store.open(
            log_id, sandbox_namespace=namespace, sandbox_name=sandbox, sandbox_uid=None, runner_session_id=runner_id
        )
    elif (
        existing.sandbox_namespace != namespace
        or existing.sandbox_name != sandbox
        or existing.runner_session_id not in (runner_id, f"r-{log_id}")
        or (existing.runner_session_id != runner_id and runner_id != str(log_id))
    ):
        raise HistoryConflictError(f"source locator disagrees for Session {log_id}")

    async with source.connect() as connection:
        ceiling = await connection.scalar(
            text("SELECT COALESCE(MAX(cursor), 0) FROM event WHERE thread_id = :id"), {"id": log_id}
        )
        assert isinstance(ceiling, int)
        cursor, first = await store.read(log_id, after_cursor=0, limit=1)
        if cursor > ceiling:
            raise HistoryConflictError(f"Service cursor {cursor} exceeds app cursor {ceiling} for Session {log_id}")
        if cursor:
            # The saved prefix was committed in contiguous, validated batches. Check both
            # boundaries before skipping it; a separate full parity pass checks the interior.
            _, last = await store.read(log_id, after_cursor=cursor - 1, limit=1)
            if len(first) != 1 or len(last) != 1:
                raise HistoryConflictError(f"stored checkpoint missing for Session {log_id}")
            source_boundaries = (
                await connection.execute(
                    text(
                        "SELECT cursor, payload::text FROM event WHERE thread_id = :id "
                        "AND cursor IN (1, :cursor) ORDER BY cursor"
                    ),
                    {"id": log_id, "cursor": cursor},
                )
            ).all()
            if len(source_boundaries) != (1 if cursor == 1 else 2):
                raise HistoryConflictError(f"app checkpoint boundary missing for Session {log_id}")
            saved_boundaries = [first[0]] if cursor == 1 else [first[0], last[0]]
            for (source_cursor, payload), saved in zip(source_boundaries, saved_boundaries, strict=True):
                entry = ParseDict(json.loads(payload), event_log_pb2.EventEntry())
                if entry.cursor != source_cursor or entry.SerializeToString(
                    deterministic=True
                ) != saved.SerializeToString(deterministic=True):
                    raise HistoryConflictError(
                        f"app checkpoint boundary changed at {source_cursor} for Session {log_id}"
                    )
        logger.info("Session %s: stored=%d app_ceiling=%d", log_id, cursor, ceiling)
        started = monotonic()
        checkpoint = cursor
        next_progress = cursor + PROGRESS_INTERVAL
        while cursor < ceiling:
            rows = (
                await connection.execute(
                    text(
                        "SELECT cursor, payload::text AS payload FROM event "
                        "WHERE thread_id = :id AND cursor > :cursor AND cursor <= :ceiling "
                        "ORDER BY cursor LIMIT :limit"
                    ),
                    {"id": log_id, "cursor": cursor, "ceiling": ceiling, "limit": PAGE_SIZE},
                )
            ).all()
            if not rows:
                raise HistoryConflictError(f"missing app Event after {cursor} for Session {log_id}")
            entries = [ParseDict(json.loads(payload), event_log_pb2.EventEntry()) for _, payload in rows]
            if any(entry.cursor != row_cursor for entry, (row_cursor, _) in zip(entries, rows, strict=True)):
                raise HistoryConflictError(f"mismatched Event cursor for Session {log_id}")
            await store.append(log_id, entries)
            cursor = entries[-1].cursor
            if cursor >= next_progress:
                logger.info(
                    "Session %s: stored=%d/%d new=%d rate=%.1f Events/s",
                    log_id,
                    cursor,
                    ceiling,
                    cursor - checkpoint,
                    (cursor - checkpoint) / max(monotonic() - started, 0.001),
                )
                next_progress = cursor + PROGRESS_INTERVAL
    logger.info("Session %s: completed through %d (+%d Events)", log_id, cursor, cursor - checkpoint)
    stored, _ = await store.read(log_id, after_cursor=0, limit=1)
    if stored < ceiling:
        raise HistoryConflictError(f"incomplete import for Session {log_id}: {stored} < {ceiling}")
    return ceiling


async def backfill(source: AsyncEngine, destination: AsyncEngine, *, namespace: str) -> tuple[int, int]:
    count, events = 0, 0
    last_id = UUID(int=0)
    while True:
        async with source.connect() as connection:
            rows = (
                await connection.execute(
                    text("SELECT id, sandbox, session_id FROM event_log WHERE id > :last_id ORDER BY id LIMIT :limit"),
                    {"last_id": last_id, "limit": PAGE_SIZE},
                )
            ).all()
        if not rows:
            return count, events
        for log_id, sandbox, runner_id in rows:
            events += await import_log(
                source, destination, namespace=namespace, log_id=log_id, sandbox=sandbox, runner_id=runner_id
            )
            count += 1
            last_id = log_id
        logger.info(
            "Visited %d Sessions (%d app Events at captured ceilings); live writes require a follow-up pass",
            count,
            events,
        )


async def run(settings: Settings) -> None:
    source = create_async_engine(settings.app_database_url, pool_pre_ping=True, hide_parameters=True)
    destination = create_async_engine(settings.sandbox_service_database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        sessions, events = await backfill(source, destination, namespace=settings.sandbox_namespace)
        logger.info("Imported %d Sessions and scanned %d app Events", sessions, events)
    finally:
        await source.dispose()
        await destination.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(Settings()))
    except ValueError, ParseError:
        # Broken data or incompatible prefix cannot be fixed by a pod restart.
        logger.exception("History import rejected inconsistent data")
        raise SystemExit(DATA_CONFLICT_EXIT_CODE) from None


if __name__ == "__main__":
    main()
