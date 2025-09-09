from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from mcp.client.session import ClientSession
from mcp.types import InitializeResult

# Type alias for functions that open an UNINITIALIZED client session under a shared stack
OpenFn = Callable[[AsyncExitStack], Awaitable[ClientSession]]


@dataclass
class ServerSlot:
    """Realized slot (initialized session + initialization metadata)."""

    session: ClientSession
    init_result: InitializeResult


@dataclass
class ServerSlotSpec:
    """Recipe for opening a server slot (returns an uninitialized session).

    The McpManager dict key is the authoritative server name; the spec does not
    need to carry a duplicate name field.
    """

    open_uninitialized: OpenFn
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def open(self, stack: AsyncExitStack) -> ServerSlot:
        async with self.lock:
            sess = await self.open_uninitialized(stack)
            init = await sess.initialize()
            return ServerSlot(session=sess, init_result=init)
