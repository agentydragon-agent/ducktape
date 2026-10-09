"""Service-history projection without app raw copies or runner contact."""

from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_bazel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from agentplane.app.testing.thread_test_support import SPEC, event_entry
from agentplane.app.threads.events.event_log import EventLogStore, EventReplicationError
from agentplane.app.threads.events.ingestion_lease import IngestionLease, IngestionLeaseLostError
from agentplane.app.threads.history_handoff import fence_raw_ingestion
from agentplane.app.threads.history_projector import HistoryProjector
from agentplane.app.threads.ingestion import Ingester, Ingestion
from agentplane.app.threads.models import Event, ThreadCheckpoint
from agentplane.app.threads.sessions import SandboxSessions
from agentplane.protocol import event_pb2
from agentplane.sandbox_service import protocol_pb2
from agentplane.sandbox_service.client import SandboxServiceClient

# gazelle:include_dep @pypi//protobuf


async def test_projection_resumes_existing_checkpoint_without_copying_raw_events(
    engine: AsyncEngine, event_logs: EventLogStore, ingestion: Ingestion, lease: IngestionLease
) -> None:
    thread = await event_logs.open("sb-1", "s-1", SPEC)
    first = event_entry(1, harness_started=event_pb2.HarnessStarted(resumed=False, pid=7))
    second = event_entry(2, turn_started=event_pb2.TurnStarted(turn_id="t1"))
    await ingestion.record(thread, [first], lease=lease)
    await fence_raw_ingestion(engine, thread)
    reader = AsyncMock(spec=SandboxServiceClient)
    reader.read_session_events.side_effect = [
        protocol_pb2.ReadSessionEventsResponse(last_cursor=2, entries=[second]),
        protocol_pb2.ReadSessionEventsResponse(last_cursor=2),
    ]
    projector = HistoryProjector(engine, cast(SandboxServiceClient, reader))
    assert (await projector.project_batch(thread, lease=lease)).through_cursor == 2
    assert (await projector.project_batch(thread, lease=lease)).through_cursor == 2
    assert reader.read_session_events.call_args.kwargs["after_cursor"] == 2
    assert await event_logs.last_cursor(thread) == 1
    async with async_sessionmaker(engine)() as session:
        assert await session.scalar(select(func.count()).select_from(Event)) == 1
        assert await session.scalar(select(ThreadCheckpoint.through_cursor)) == 2


async def test_failed_projection_can_retry_without_advancing_checkpoint(
    engine: AsyncEngine, event_logs: EventLogStore, lease: IngestionLease
) -> None:
    thread = await event_logs.open("sb-1", "s-1", SPEC)
    entry = event_entry(1, harness_started=event_pb2.HarnessStarted(resumed=False, pid=7))
    await fence_raw_ingestion(engine, thread)
    reader = AsyncMock(spec=SandboxServiceClient)
    reader.read_session_events.return_value = protocol_pb2.ReadSessionEventsResponse(last_cursor=1, entries=[entry])
    projector = HistoryProjector(engine, cast(SandboxServiceClient, reader))
    with (
        patch("agentplane.app.threads.history_projector.record_thread_fold", side_effect=ValueError("fold failed")),
        pytest.raises(ValueError, match="fold failed"),
    ):
        await projector.project_batch(thread, lease=lease)
    async with async_sessionmaker(engine)() as session:
        assert await session.scalar(select(ThreadCheckpoint.through_cursor)) is None
    assert (await projector.project_batch(thread, lease=lease)).through_cursor == 1
    assert await event_logs.last_cursor(thread) == 0


async def test_expired_owner_cannot_project(
    engine: AsyncEngine, event_logs: EventLogStore, ingestion: Ingestion, lease: IngestionLease
) -> None:
    thread = await event_logs.open("sb-1", "s-1", SPEC)
    await fence_raw_ingestion(engine, thread)
    reader = AsyncMock(spec=SandboxServiceClient)
    reader.read_session_events.return_value = protocol_pb2.ReadSessionEventsResponse(
        last_cursor=1, entries=[event_entry(1, harness_started=event_pb2.HarnessStarted(resumed=False, pid=7))]
    )
    await ingestion.release(lease)
    with pytest.raises(IngestionLeaseLostError):
        await HistoryProjector(engine, cast(SandboxServiceClient, reader)).project_batch(thread, lease=lease)
    async with async_sessionmaker(engine)() as session:
        assert await session.scalar(select(ThreadCheckpoint.through_cursor)) is None


@pytest.mark.parametrize("case", ["gap", "source_sequence", "beyond_watermark"])
async def test_invalid_history_does_not_advance_projection(
    engine: AsyncEngine, event_logs: EventLogStore, lease: IngestionLease, case: str
) -> None:
    thread = await event_logs.open("sb-1", "s-1", SPEC)
    entry = event_entry(1, harness_started=event_pb2.HarnessStarted(resumed=False, pid=7))
    if case == "source_sequence":
        entry.origin.sequence = 9
    await fence_raw_ingestion(engine, thread)
    reader = AsyncMock(spec=SandboxServiceClient)
    reader.read_session_events.return_value = protocol_pb2.ReadSessionEventsResponse(
        last_cursor=0 if case == "beyond_watermark" else 1, entries=[] if case == "gap" else [entry]
    )
    with pytest.raises(EventReplicationError):
        await HistoryProjector(engine, cast(SandboxServiceClient, reader)).project_batch(thread, lease=lease)
    assert await event_logs.last_cursor(thread) == 0


async def test_projection_requires_fence_and_final_raw_coverage(
    engine: AsyncEngine, event_logs: EventLogStore, ingestion: Ingestion, lease: IngestionLease
) -> None:
    thread = await event_logs.open("sb-1", "s-1", SPEC)
    reader = AsyncMock(spec=SandboxServiceClient)
    projector = HistoryProjector(engine, cast(SandboxServiceClient, reader))
    with pytest.raises(EventReplicationError, match="must be fenced"):
        await projector.project_batch(thread, lease=lease)
    reader.read_session_events.assert_not_awaited()
    await ingestion.record(
        thread, [event_entry(1, harness_started=event_pb2.HarnessStarted(resumed=False, pid=7))], lease=lease
    )
    assert await fence_raw_ingestion(engine, thread) == 1
    reader.read_session_events.return_value = protocol_pb2.ReadSessionEventsResponse(last_cursor=0)
    with pytest.raises(ConnectionError, match="final raw cursor"):
        await projector.project_batch(thread, lease=lease)


async def test_supervisor_resumes_fenced_deleted_sandbox_without_runner_contact(
    engine: AsyncEngine, event_logs: EventLogStore, ingestion: Ingestion
) -> None:
    thread = await event_logs.open("deleted-sandbox", "s-1", SPEC)
    await fence_raw_ingestion(engine, thread)
    reader = AsyncMock(spec=SandboxServiceClient)
    reader.read_session_events.side_effect = [
        protocol_pb2.ReadSessionEventsResponse(
            last_cursor=1, entries=[event_entry(1, harness_started=event_pb2.HarnessStarted(resumed=False, pid=7))]
        ),
        protocol_pb2.ReadSessionEventsResponse(last_cursor=1),
    ]
    runners = Mock(spec=SandboxSessions)
    runners.running.return_value = set()
    for _ in range(2):
        coordinator = Ingester(
            runners=cast(SandboxSessions, runners),
            event_logs=event_logs,
            ingestion=ingestion,
            history_projector=HistoryProjector(engine, cast(SandboxServiceClient, reader)),
        )
        try:
            await coordinator.reconcile()
        finally:
            await coordinator.close()
    assert reader.read_session_events.call_args_list[0].kwargs["after_cursor"] == 0
    assert reader.read_session_events.call_args_list[1].kwargs["after_cursor"] == 1
    runners.client.assert_not_called()
    assert await event_logs.last_cursor(thread) == 0
    async with async_sessionmaker(engine)() as session:
        assert await session.scalar(select(ThreadCheckpoint.through_cursor)) == 1


if __name__ == "__main__":
    pytest_bazel.main()
