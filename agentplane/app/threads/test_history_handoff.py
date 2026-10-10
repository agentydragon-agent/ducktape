"""The database fence survives old writers and replaceable ingestion leases."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_bazel
from google.protobuf.json_format import MessageToDict
from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from agentplane.app.testing.retained_history import seed_retained_session
from agentplane.app.testing.thread_test_support import SPEC, event_entry
from agentplane.app.threads.events.ingestion_lease import IngestionLease
from agentplane.app.threads.history_handoff import fence_raw_ingestion
from agentplane.app.threads.ingestion import Ingestion
from agentplane.app.threads.models import Event, FeedState
from agentplane.protocol import event_pb2
from agentplane.runner import protocol_pb2

# gazelle:include_dep @pypi//protobuf


async def test_fence_is_idempotent_and_blocks_old_writer_after_lease_reacquisition(
    engine: AsyncEngine, lease: IngestionLease
) -> None:
    thread = await seed_retained_session(engine)
    ingestion = Ingestion(engine)
    entry = event_entry(1, harness_started=event_pb2.HarnessStarted(resumed=False, pid=7))
    async with engine.begin() as connection:
        await connection.execute(
            insert(Event).values(
                thread_id=thread,
                cursor=1,
                at=entry.event.at.ToDatetime(tzinfo=UTC),
                kind="harness_started",
                payload=MessageToDict(entry),
            )
        )
    assert await fence_raw_ingestion(engine, thread) == 1
    assert await fence_raw_ingestion(engine, thread) == 1
    await ingestion.release(lease)
    replacement = await ingestion.acquire("sb-1", timedelta(minutes=1))
    assert replacement is not None
    with pytest.raises(DBAPIError, match="app raw ingestion fenced"):
        async with engine.begin() as connection:
            await connection.execute(
                insert(Event).values(
                    thread_id=thread, cursor=2, at=datetime(2026, 1, 1, tzinfo=UTC), kind="", payload={}
                )
            )
    with pytest.raises(DBAPIError, match="app raw ingestion fenced"):
        async with engine.begin() as connection:
            await connection.execute(
                insert(FeedState).values(
                    thread_id=thread, attached=MessageToDict(protocol_pb2.Attached(spec=SPEC)), end=None
                )
            )
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.max(Event.cursor)).where(Event.thread_id == thread)) == 1


async def test_fence_drains_an_inflight_old_raw_transaction(engine: AsyncEngine) -> None:
    thread = await seed_retained_session(engine)
    async with engine.begin() as old_writer:
        # The trigger takes the same SHARE lock for an old binary or direct SQL.
        await old_writer.execute(
            insert(Event).values(thread_id=thread, cursor=1, at=datetime(2026, 1, 1, tzinfo=UTC), kind="", payload={})
        )
        pending = asyncio.create_task(fence_raw_ingestion(engine, thread))
        await asyncio.sleep(0)
    assert await asyncio.wait_for(pending, timeout=10) == 1
    with pytest.raises(DBAPIError, match="app raw ingestion fenced"):
        async with engine.begin() as old_writer:
            await old_writer.execute(
                insert(Event).values(
                    thread_id=thread, cursor=2, at=datetime(2026, 1, 1, tzinfo=UTC), kind="", payload={}
                )
            )


if __name__ == "__main__":
    pytest_bazel.main()
