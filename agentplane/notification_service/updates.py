"""Commit-driven queue wakeups. NOTIFY is an invalidation, never the durable delivery."""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import asyncpg
from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, wait_exponential

CHANNEL = "agentplane_notification_work"
logger = logging.getLogger(__name__)


# Authentication/configuration errors are not transient connection failures.
CONNECTION_ERRORS = (OSError, TimeoutError, asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError)


def reconnect_failed(state: RetryCallState) -> None:
    assert state.outcome is not None
    error = state.outcome.exception()
    # Exception text may contain the DSN or credentials; type and SQLSTATE are safe diagnostics.
    logger.warning(
        "notification listener reconnect failed: type=%s sqlstate=%s attempt=%d",
        type(error).__name__,
        error.sqlstate if isinstance(error, asyncpg.PostgresError) else None,
        state.attempt_number,
    )


async def notify(session: AsyncSession) -> None:
    # Empty payload; delivery content and scheduling live in the committed rows.
    await session.execute(select(func.pg_notify(CHANNEL, "")))


class Wakeups:
    def __init__(self, url: URL) -> None:
        self._dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
        self._connection: asyncpg.Connection[Any] | None = None
        self._lost = asyncio.Event()
        self._waiters: set[asyncio.Event] = set()
        self._listening = False

    @property
    def connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed() and not self._lost.is_set()

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Event]:
        changed = asyncio.Event()
        self._waiters.add(changed)
        try:
            yield changed
        finally:
            self._waiters.remove(changed)

    def _wake(self) -> None:
        for changed in self._waiters:
            changed.set()

    def _notified(self, _connection: object, _pid: int, _channel: str, _payload: object) -> None:
        self._wake()

    def _terminated(self, _connection: object) -> None:
        self._lost.set()
        self._wake()

    async def _connect(self) -> None:
        connection = await asyncpg.connect(
            self._dsn, timeout=10, server_settings={"application_name": "agentplane-notification-wakeups"}
        )
        try:
            connection.add_termination_listener(self._terminated)
            await connection.add_listener(CHANNEL, self._notified)
            if connection.is_closed():
                raise ConnectionError("notification listener disconnected during startup")
        except BaseException:
            await connection.close(timeout=2)
            raise
        self._connection = connection
        self._lost.clear()
        # Register LISTEN before the catch-up read: replay commits made during startup/reconnect.
        self._wake()

    @asynccontextmanager
    async def listen(self) -> AsyncIterator[None]:
        if self._listening:
            raise RuntimeError("notification listener already started")
        self._listening = True
        try:
            await self._connect()
            async with asyncio.TaskGroup() as tasks:
                task = tasks.create_task(self._recover(), name="notification-listener")
                try:
                    yield
                finally:
                    task.cancel()
        finally:
            try:
                await self._disconnect()
            finally:
                self._listening = False

    async def _disconnect(self) -> None:
        if self._connection is not None:
            connection, self._connection = self._connection, None
            await connection.close(timeout=2)

    async def _recover(self) -> None:
        while True:
            await self._lost.wait()
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(CONNECTION_ERRORS),
                wait=wait_exponential(min=1, max=30),
                before_sleep=reconnect_failed,
                reraise=True,
            ):
                with attempt:
                    await self._disconnect()
                    await self._connect()
