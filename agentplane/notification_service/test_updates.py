"""Real PostgreSQL commit wakeups, replica fanout, recovery and durable retry deadlines."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import asyncpg
import pytest
import pytest_bazel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from agentplane.notification_service.db import Inbox
from agentplane.notification_service.models import ActionsSource, DestinationRef, Subscribe
from agentplane.notification_service.store import Store
from agentplane.notification_service.updates import Wakeups, notify
from agentplane.workload_auth.principal import WorkloadPrincipal

PRINCIPAL = WorkloadPrincipal("test", "owner", "system:serviceaccount:test:owner", "pod", "pod-uid")
BODY = Subscribe(
    destination_ref=DestinationRef(namespace="test", name="sandbox", uid="sandbox-uid"),
    session_id="session",
    idempotency_key="wakeups",
    source=ActionsSource(provider="actions", request_id=uuid4()),
)


async def terminate_listener(store: Store) -> None:
    async with store.sessions.begin() as session:
        await session.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND application_name = 'agentplane-notification-wakeups'"
            )
        )


async def test_notify_is_commit_scoped_and_fans_out(engine: AsyncEngine, store: Store) -> None:
    first, second = Wakeups(engine.url), Wakeups(engine.url)
    async with first.listen(), second.listen():
        with first.subscribe() as a, second.subscribe() as b:
            async with store.sessions.begin() as session:
                await notify(session)
                assert not a.is_set()
                assert not b.is_set()
                await session.rollback()
            assert not a.is_set()
            assert not b.is_set()
            async with store.sessions.begin() as session:
                await notify(session)
                assert not a.is_set()
                assert not b.is_set()
            async with asyncio.timeout(10):
                await a.wait()
                await b.wait()


async def test_startup_and_reconnect_drain_durable_work(store: Store) -> None:
    # Acceptance before LISTEN cannot be recovered from NOTIFY; it is recovered from the row.
    sub = await store.subscribe(PRINCIPAL, BODY)
    with store.wakeups.subscribe() as changed:
        async with store.wakeups.listen():
            assert changed.is_set()
            claim = await store.claim()
            assert claim is not None
            assert claim.id == sub.inbox_id
            # A worker dying with a claim leaves a lease deadline, not a lost in-memory job.
            next_work_at = await store.get_next_work_at()
            assert next_work_at == claim.claim_until
            assert datetime.now(UTC) < next_work_at <= datetime.now(UTC) + timedelta(seconds=30)
        async with store.sessions.begin() as session:
            inbox = await session.get(Inbox, claim.id)
            assert inbox is not None
            inbox.claim_until = datetime.now(UTC) - timedelta(seconds=1)
            await notify(session)
        changed.clear()
        async with store.wakeups.listen():
            assert changed.is_set()
            recovered = await store.claim()
            assert recovered is not None
            assert recovered.claim != claim.claim


async def test_listener_context_cleans_up_on_error_and_cancellation(store: Store) -> None:
    async def fail() -> None:
        async with store.wakeups.listen():
            assert store.wakeups.connected
            raise ValueError("body failed")

    with pytest.RaisesGroup(pytest.RaisesExc(ValueError, match="body failed")):
        await fail()
    assert not store.wakeups.connected
    entered = asyncio.Event()

    async def wait() -> None:
        async with store.wakeups.listen():
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(wait())
    try:
        async with asyncio.timeout(10):
            await entered.wait()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not store.wakeups.connected
    # Neither exceptional exit leaves a reconnect task or prevents subsequent scoped use.
    async with store.wakeups.listen():
        assert store.wakeups.connected
    assert not store.wakeups.connected


async def test_listener_recovers_without_a_new_notification_and_logs_safe_retry_diagnostics(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    async with store.wakeups.listen():
        connect = store.wakeups._connect
        attempts = 0

        async def reconnect() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise asyncpg.CannotConnectNowError("secret-bearing connection details")
            await connect()

        with patch.object(store.wakeups, "_connect", side_effect=reconnect), store.wakeups.subscribe() as changed:
            await terminate_listener(store)
            async with asyncio.timeout(10):
                while attempts < 2 or not store.wakeups.connected:
                    await changed.wait()
                    changed.clear()
        assert attempts == 2
    assert "CannotConnectNowError" in caplog.text
    assert "sqlstate=57P03" in caplog.text
    assert "secret-bearing" not in caplog.text


@pytest.mark.parametrize("error", [ValueError("programming error"), asyncpg.InvalidPasswordError("bad credentials")])
async def test_nontransient_reconnect_errors_escape_listener_scope(store: Store, error: Exception) -> None:
    with pytest.RaisesGroup(pytest.RaisesExc(type(error))):
        async with store.wakeups.listen():
            with patch.object(store.wakeups, "_connect", side_effect=error):
                await terminate_listener(store)
                async with asyncio.timeout(10):
                    await asyncio.Event().wait()
    assert not store.wakeups.connected


async def test_cancelled_inbox_has_no_periodic_work(store: Store) -> None:
    sub = await store.subscribe(PRINCIPAL, BODY)
    claim = await store.claim()
    assert claim is not None
    await store.change(PRINCIPAL.account, sub.id, None)
    await store.release(claim, None)
    assert await store.get_next_work_at() is None
    assert await store.claim() is None
    async with store.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Inbox)) == 1


if __name__ == "__main__":
    pytest_bazel.main()
