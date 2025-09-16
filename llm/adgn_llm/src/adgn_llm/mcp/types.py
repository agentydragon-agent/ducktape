from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import AsyncContextManager, Callable

from mcp.client.session import ClientSession
from mcp.types import InitializeResult

# Canonical OpenFn protocol — single lifetime boundary
#
# Design decision: every transport factory (OpenFn) MUST accept the manager's
# AsyncExitStack and return an async context manager yielding an
# UNINITIALIZED mcp.client.session.ClientSession when entered via that stack.
#
# Rationale:
# - mcp's ServerSession / ClientSession and transport helpers (stdio_client, sse_client)
#   create their own anyio task-groups and cancel scopes during __aenter__.
# - anyio enforces that a cancel scope must be *entered* and *exited* in the
#   same task. If different tasks perform enter/exit, a RuntimeError is raised
#   ("Attempted to exit cancel scope in a different task than it was entered in").
# - To make resource lifetime deterministic and avoid subtle cross-task races,
#   the McpManager is the single lifetime owner. Openers therefore must register
#   their subordinate contexts (streams, task-groups, sessions) by calling
#   stack.enter_async_context(...) so enter/exit happen under the manager's
#   AsyncExitStack and within the same cancel scope/task.
#
# This file's ServerSlotSpec.open() will call stack.enter_async_context(open_uninitialized(stack))
# and then call ClientSession.initialize() — this is the ONE supported API.
# See related modules:
# - adgn_llm/mcp/inproc_transport.py (in-proc FastMCP wiring)
# - adgn_llm/mini_codex/mcp_manager.py (slot_from_spec implementations)
# - mcp/shared/session.py (BaseSession: creates its own task group on enter)
# - mcp/server/lowlevel/server.py (Server.run uses AsyncExitStack + task group)
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
