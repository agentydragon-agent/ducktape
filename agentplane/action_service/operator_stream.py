"""Shared operator SSE loop: committed invalidations, snapshots, and credential rechecks.

A LISTEN notification is only a wakeup. Subscribe before the first read and re-read canonical
state after every commit; reconnect sends a fresh snapshot rather than relying on replay.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from fastapi.responses import StreamingResponse

from agentplane.action_service.updates import ActionSubscription


def snapshot_stream(
    subscribe: Callable[[], AbstractContextManager[ActionSubscription]],
    read: Callable[[], Awaitable[bytes]],
    authorized: Callable[[], Awaitable[bool]],
    *,
    changed_event: bool = False,
    refresh_at: Callable[[], datetime | None] | None = None,
) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        with subscribe() as subscription:
            changed = subscription.changed
            while True:
                changed.clear()  # Before read: commits during a read remain set.
                subscription.check_available()
                if not await authorized():
                    return
                snapshot = await read()
                subscription.check_available()
                yield b"event: snapshot\ndata: " + snapshot + b"\n\n"
                while not changed.is_set():
                    try:
                        deadline = refresh_at() if refresh_at is not None else None
                        timeout = 5.0
                        if deadline is not None:
                            timeout = min(timeout, max(0.0, (deadline - datetime.now(UTC)).total_seconds()))
                        async with asyncio.timeout(timeout):
                            await changed.wait()
                    except TimeoutError:
                        if deadline is not None and datetime.now(UTC) >= deadline:
                            break  # A computed state (e.g. token expiry) changed without a database write.
                        subscription.check_available()
                        if not await authorized():
                            return
                        subscription.check_available()
                        yield b": keepalive\n\n"
                subscription.check_available()
                if changed_event:
                    yield b"event: changed\ndata: {}\n\n"

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
