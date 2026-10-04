"""Owned LISTEN connection; notifications invalidate durable state rather than replace it."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from sqlalchemy.engine import URL
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, wait_exponential

logger = logging.getLogger(__name__)
CONNECTION_ERRORS = (OSError, TimeoutError, asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError)


class PostgresListener:
    """Adapters own payload parsing/fanout; invalidate readers on both connection loss and registration."""

    def __init__(
        self,
        url: URL,
        *,
        channel: str,
        application_name: str,
        notified: Callable[[str], None],
        invalidated: Callable[[], None],
    ) -> None:
        self._dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
        self._channel = channel
        self._application_name = application_name
        self._notified = notified
        self._invalidated = invalidated
        self._connection: asyncpg.Connection[Any] | None = None
        self._lost = asyncio.Event()
        self._listening = False

    @property
    def connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed() and not self._lost.is_set()

    async def start(self) -> None:
        """Establish LISTEN before returning. Standalone users own recovery and must close."""
        if self._connection is not None:
            raise RuntimeError("PostgreSQL listener already started")
        connection = await asyncpg.connect(
            self._dsn, timeout=10, server_settings={"application_name": self._application_name}
        )
        try:
            connection.add_termination_listener(self._terminated)
            await connection.add_listener(self._channel, self._receive)
            if connection.is_closed():
                raise ConnectionError("PostgreSQL listener disconnected during startup")
        except BaseException:
            await connection.close(timeout=2)
            raise
        self._connection = connection
        self._lost.clear()
        # LISTEN first, then catch up: commits during startup/reconnect are only in durable state.
        self._invalidated()

    async def close(self) -> None:
        self._lost.set()
        self._invalidated()
        if self._connection is not None:
            connection, self._connection = self._connection, None
            await connection.close(timeout=2)

    @asynccontextmanager
    async def listen(self) -> AsyncIterator[None]:
        """Fail startup immediately; supervise recovery and close on every scope exit."""
        if self._listening or self._connection is not None:
            raise RuntimeError("PostgreSQL listener already started")
        self._listening = True
        try:
            await self.start()
            async with asyncio.TaskGroup() as tasks:
                task = tasks.create_task(self._recover(), name=self._application_name)
                try:
                    yield
                finally:
                    task.cancel()
        finally:
            try:
                await self.close()
            finally:
                self._listening = False

    def _receive(self, _connection: object, _pid: int, _channel: str, payload: str) -> None:
        self._notified(payload)

    def _terminated(self, connection: object) -> None:
        # An old connection's queued termination callback must not invalidate its replacement.
        if connection is self._connection:
            self._lost.set()
            self._invalidated()

    def _reconnect_failed(self, state: RetryCallState) -> None:
        assert state.outcome is not None
        error = state.outcome.exception()
        # Exception text can contain credentials. Log only the configured name, type and SQLSTATE.
        logger.warning(
            "PostgreSQL listener %s reconnect failed: type=%s sqlstate=%s attempt=%d",
            self._application_name,
            type(error).__name__,
            error.sqlstate if isinstance(error, asyncpg.PostgresError) else None,
            state.attempt_number,
        )

    async def _recover(self) -> None:
        while True:
            await self._lost.wait()
            await self.close()
            # Back off after a lost connection as well as after unsuccessful reconnects.
            await asyncio.sleep(1)
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(CONNECTION_ERRORS),
                wait=wait_exponential(min=1, max=30),
                before_sleep=self._reconnect_failed,
                reraise=True,
            ):
                with attempt:
                    await self.start()
