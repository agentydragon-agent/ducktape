"""Delivery-policy tests with real durable inbox state and worker scheduling."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, create_autospec
from uuid import uuid4

import pytest
import pytest_bazel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from agentplane.action_service.models import ActionEventView, ActionState
from agentplane.notification_service.db import Entry, Inbox
from agentplane.notification_service.models import ActionsSource, DestinationRef, Subscribe
from agentplane.notification_service.service import Service
from agentplane.notification_service.settings import NoticeDebounceSettings
from agentplane.notification_service.sources.actions import Actions
from agentplane.notification_service.store import COMPACT_NOTICE_MARKER, Store
from agentplane.protocol import event_log_pb2, event_pb2
from agentplane.runner import protocol_pb2 as runner_pb2
from agentplane.sandbox_service.client import Runner, SandboxServiceClient
from agentplane.workload_auth.principal import WorkloadPrincipal

# gazelle:include_dep @pypi//protobuf

PRINCIPAL = WorkloadPrincipal("test", "owner", "system:serviceaccount:test:owner", "pod", "pod-uid")
BODY = Subscribe(
    destination_ref=DestinationRef(namespace="test", name="sandbox", uid="sandbox-uid"),
    session_id="session",
    idempotency_key="debounce",
    source=ActionsSource(provider="actions", request_id=uuid4()),
)


@pytest.fixture
async def service(store: Store) -> Service:
    return Service(
        store, create_autospec(Actions), create_autospec(SandboxServiceClient), notice_debounce=NoticeDebounceSettings()
    )


def events(count: int) -> list[ActionEventView]:
    return [
        ActionEventView(sequence=i, state=ActionState.DECISION_PENDING, at=datetime.now(UTC))
        for i in range(1, count + 1)
    ]


@pytest.mark.parametrize("quiet_seconds", [0, 60])
async def test_notice_debounce_deadline_is_durable_and_reads_are_immediate(
    service: Service, engine: AsyncEngine, quiet_seconds: float
) -> None:
    store = service.store
    service.notice_debounce = NoticeDebounceSettings(quiet_seconds=quiet_seconds, max_wait_seconds=300)
    subscription = await store.subscribe(PRINCIPAL, BODY)
    claim = await store.claim()
    assert claim is not None
    source = await store.source(claim)
    assert source is not None
    await store.record(claim, source, events(2))
    now = datetime.now(UTC)
    first, last = now - timedelta(seconds=120), now - timedelta(seconds=1)
    async with store.sessions.begin() as session:
        await session.execute(update(Entry).where(Entry.cursor == 1).values(created_at=first))
        await session.execute(update(Entry).where(Entry.cursor == 2).values(created_at=last))
    # Matching the same events through another subscription must not extend the quiet window.
    overlap = await store.subscribe(PRINCIPAL, BODY.model_copy(update={"idempotency_key": "overlap"}))
    other_source = await store.source(claim)
    assert other_source is not None
    assert other_source.id == overlap.id
    await store.record(claim, other_source, events(2))
    page = await store.read(PRINCIPAL.account, subscription.inbox_id, 0, 128)
    assert [entry.cursor for entry in page.entries] == [1, 2]
    assert page.inbox.acknowledged == 0
    assert page.notice is None
    # Remove source deadlines, so only notice delivery can schedule this inbox.
    await store.change(PRINCIPAL.account, subscription.id, None)
    await store.change(PRINCIPAL.account, overlap.id, None)
    await store.release(claim, None, notice_due_at=await service.get_notice_due_at(claim))
    restarted = Service(Store(engine), service.actions, service.sandboxes, notice_debounce=service.notice_debounce)
    recovered = restarted.store
    async with recovered.sessions() as session:
        inbox = await session.get(Inbox, claim.id)
        assert inbox is not None
        assert inbox.next_attempt == last + timedelta(seconds=quiet_seconds)
    if quiet_seconds:
        assert await recovered.get_next_work_at() == last + timedelta(seconds=quiet_seconds)
        assert await recovered.claim() is None
    # Age just the quiet window; recovery needs no process-local timer or new NOTIFY.
    async with recovered.sessions.begin() as session:
        await session.execute(update(Inbox).where(Inbox.id == claim.id).values(next_attempt=now))
    claim = await recovered.claim()
    assert claim is not None
    if quiet_seconds:
        assert await restarted.prepare_notice(claim) is None
        async with recovered.sessions.begin() as session:
            await session.execute(update(Entry).where(Entry.cursor == 2).values(created_at=now - timedelta(seconds=61)))
    notice = await restarted.prepare_notice(claim)
    assert notice is not None
    assert notice.through_cursor == 2


async def test_notice_max_wait_and_inflight_notice_are_not_extended(service: Service) -> None:
    store = service.store
    service.notice_debounce = NoticeDebounceSettings(quiet_seconds=60, max_wait_seconds=300)
    subscription = await store.subscribe(PRINCIPAL, BODY)
    claim = await store.claim()
    assert claim is not None
    source = await store.source(claim)
    assert source is not None
    await store.record(claim, source, events(2))
    assert await service.prepare_notice(claim) is None
    # A recent entry cannot postpone an older pending entry beyond the maximum wait.
    async with store.sessions.begin() as session:
        await session.execute(
            update(Entry).where(Entry.cursor == 1).values(created_at=datetime.now(UTC) - timedelta(seconds=301))
        )
    notice = await service.prepare_notice(claim)
    assert notice is not None
    assert notice.through_cursor == 2
    await store.record(claim, source, events(3))
    retry = await service.prepare_notice(claim)
    assert retry is not None
    assert (retry.command_id, retry.text, retry.through_cursor) == (notice.command_id, notice.text, 2)
    await store.receipt(
        claim,
        notice,
        event_log_pb2.EventEntry(
            cursor=1,
            event=event_pb2.Event(
                harness_user_message_confirmed=event_pb2.HarnessUserMessageConfirmed(
                    origin_command_ids=[str(notice.command_id)]
                )
            ),
        ),
    )
    # The next burst has its own window; the already covered old entry cannot force it due.
    assert await service.prepare_notice(claim) is None
    await store.change(PRINCIPAL.account, subscription.id, None)
    await store.acknowledge(PRINCIPAL.account, subscription.inbox_id, 3)
    await store.release(claim, None, notice_due_at=await service.get_notice_due_at(claim))
    assert await store.get_next_work_at() is None


@pytest.mark.parametrize("supports_compact", [False, True])
async def test_notice_contract_respects_persisted_session_and_retries(
    service: Service, supports_compact: bool
) -> None:
    store = service.store
    service.notice_debounce = NoticeDebounceSettings(quiet_seconds=0)
    subscription = await store.subscribe(PRINCIPAL, BODY)
    claim = await store.claim()
    assert claim is not None
    source = await store.source(claim)
    assert source is not None
    await store.record(claim, source, events(1))
    runner = create_autospec(Runner)
    runner.list_sessions = AsyncMock(
        return_value=[
            runner_pb2.SessionSummary(
                session_id=claim.session_id,
                spec=runner_pb2.SessionSpec(instructions=COMPACT_NOTICE_MARKER if supports_compact else "legacy"),
            )
        ]
    )
    notice = await service.prepare_notice(claim, runner=runner)
    assert notice is not None
    assert notice.through_cursor == 1
    assert ("GET /v1/inboxes/" not in notice.text) == supports_compact
    assert str(subscription.inbox_id) in notice.text
    runner.list_sessions = AsyncMock(
        return_value=[
            runner_pb2.SessionSummary(
                session_id=claim.session_id,
                spec=runner_pb2.SessionSpec(instructions="legacy" if supports_compact else COMPACT_NOTICE_MARKER),
            )
        ]
    )
    retry = await service.prepare_notice(claim, runner=runner)
    assert retry is not None
    assert (retry.command_id, retry.text) == (notice.command_id, notice.text)


if __name__ == "__main__":
    pytest_bazel.main()
