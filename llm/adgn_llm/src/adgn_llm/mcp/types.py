from __future__ import annotations
import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Callable, AsyncContextManager
from mcp.client.session import ClientSession
from mcp.types import InitializeResult


# Canonical OpenFn protocol: factories MUST return an async context manager
# that yields an uninitialized ClientSession when entered by the caller.
OpenFn = Callable[[AsyncExitStack], AsyncContextManager[ClientSession]]


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
            # open_uninitialized follows the canonical protocol and returns an
            # async context manager that yields an UNINITIALIZED ClientSession when
            # entered. Enter it via the provided AsyncExitStack so the same lifetime
            # boundary manages session teardown.
            sess = await stack.enter_async_context(self.open_uninitialized(stack))
            init = await sess.initialize()
            return ServerSlot(session=sess, init_result=init)
