"""Service-history projection without app raw copies or runner contact."""

from datetime import UTC
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
from agentplane.app.threads.models import Event, EventLog, ThreadCheckpoint
from agentplane.app.threads.sessions import SandboxSessions
from agentplane.app.threads.store import ThreadStore
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


async def test_projection_updates_activity_atomically_and_ignores_tool_output(
    engine: AsyncEngine, event_logs: EventLogStore, ingestion: Ingestion, lease: IngestionLease
) -> None:
    thread = await event_logs.open("sb-1", "activity", SPEC)
    first = [
        event_entry(1, turn_started=event_pb2.TurnStarted(turn_id="turn", model=SPEC.model)),
        event_entry(2, item_started=event_pb2.ItemStarted(item_id="call", kind=event_pb2.ITEM_KIND_TOOL_CALL)),
    ]
    await ingestion.record(thread, first, lease=lease)
    await fence_raw_ingestion(engine, thread)
    activity = event_entry(3, tool_arguments=event_pb2.ToolArguments(item_id="call", arguments_json='{"x":"y"}'))
    reader = AsyncMock(spec=SandboxServiceClient)
    reader.read_session_events.return_value = protocol_pb2.ReadSessionEventsResponse(last_cursor=3, entries=[activity])
    projector = HistoryProjector(engine, cast(SandboxServiceClient, reader))
    # Fail after the fold and activity write: both must roll back together.
    with (
        patch("agentplane.app.threads.history_projector.notify", side_effect=RuntimeError("commit interrupted")),
        pytest.raises(RuntimeError, match="commit interrupted"),
    ):
        await projector.project_batch(thread, lease=lease)
    async with async_sessionmaker(engine)() as session:
        assert await session.scalar(select(ThreadCheckpoint.through_cursor)) == 2
        assert await session.scalar(select(EventLog.last_model_activity_at)) == first[-1].event.at.ToDatetime(
            tzinfo=UTC
        )
    assert (await projector.project_batch(thread, lease=lease)).through_cursor == 3
    reader.read_session_events.return_value = protocol_pb2.ReadSessionEventsResponse(
        last_cursor=4,
        entries=[event_entry(4, tool_output_delta=event_pb2.ToolOutputDelta(item_id="call", text="still running"))],
    )
    assert (await projector.project_batch(thread, lease=lease)).through_cursor == 4
    reader.read_session_events.return_value = protocol_pb2.ReadSessionEventsResponse(last_cursor=4)
    assert (await projector.project_batch(thread, lease=lease)).through_cursor == 4
    async with async_sessionmaker(engine)() as session:
        assert await session.scalar(select(EventLog.last_model_activity_at)) == activity.event.at.ToDatetime(tzinfo=UTC)
        assert await session.scalar(select(ThreadCheckpoint.through_cursor)) == 4
        assert await session.scalar(select(func.count()).select_from(Event)) == 2


async def test_thread_metadata_survives_handoff_and_projection_retry(
    engine: AsyncEngine, event_logs: EventLogStore, ingestion: Ingestion, lease: IngestionLease
) -> None:
    thread = await event_logs.open("sb-1", "summary", SPEC)
    sibling = await event_logs.open("sb-1", "unfenced", SPEC)
    first = [
        event_entry(1, turn_started=event_pb2.TurnStarted(turn_id="one", model=SPEC.model)),
        event_entry(2, turn_completed=event_pb2.TurnCompleted(turn_id="one", status=event_pb2.TURN_STATUS_COMPLETED)),
    ]
    await ingestion.record(thread, first, lease=lease)
    await ingestion.record(sibling, first, lease=lease)
    store = ThreadStore(engine)
    before = await store.get_thread(thread)
    assert before is not None
    await fence_raw_ingestion(engine, thread)
    assert await store.get_thread(thread) == before
    assert (await store.list_threads())[0].last_cursor == 2
    later = [
        event_entry(3, turn_started=event_pb2.TurnStarted(turn_id="two", model=SPEC.model)),
        event_entry(4, turn_completed=event_pb2.TurnCompleted(turn_id="two", status=event_pb2.TURN_STATUS_INTERRUPTED)),
    ]
    # Last-event time is max timestamp, while last-turn status is cursor ordered.
    for entry in later:
        entry.event.at.CopyFrom(first[0].event.at)
    reader = AsyncMock(spec=SandboxServiceClient)
    reader.read_session_events.return_value = protocol_pb2.ReadSessionEventsResponse(last_cursor=4, entries=later)
    projector = HistoryProjector(engine, cast(SandboxServiceClient, reader))
    with (
        patch("agentplane.app.threads.history_projector.notify", side_effect=RuntimeError("interrupted")),
        pytest.raises(RuntimeError, match="interrupted"),
    ):
        await projector.project_batch(thread, lease=lease)
    assert await store.get_thread(thread) == before
    await projector.project_batch(thread, lease=lease)
    after = await store.get_thread(thread)
    assert after is not None
    assert after.last_cursor == 4
    assert after.last_event_at == before.last_event_at
    assert after.last_turn_status == "TURN_STATUS_INTERRUPTED"
    views = {view.id: view for view in await store.list_threads()}
    assert views[thread] == after
    assert views[sibling].last_cursor == 2
    assert views[sibling].last_turn_status == "TURN_STATUS_COMPLETED"
    renamed = await store.rename(thread, "retained")
    assert renamed.last_cursor == 4
    assert renamed.last_turn_status == after.last_turn_status
    assert await event_logs.last_cursor(thread) == 2


if __name__ == "__main__":
    pytest_bazel.main()
