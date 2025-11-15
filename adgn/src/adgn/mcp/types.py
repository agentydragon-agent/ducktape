from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass, field
import logging

from mcp.client.session import ClientSession
from mcp.types import InitializeResult

# Canonical OpenFn protocol — single lifetime boundary
#
# Design decision: every transport factory (OpenFn) MUST accept an AsyncExitStack
# from the lifetime owner (e.g., container/runner) and return an async context manager
# yielding an UNINITIALIZED mcp.client.session.ClientSession when entered via that stack.
#
# Rationale:
# - mcp's ServerSession / ClientSession and transport helpers (stdio_client, sse_client)
#   create their own anyio task-groups and cancel scopes during __aenter__.
# - anyio enforces that a cancel scope must be entered and exited in the same task.
#   To keep lifetime deterministic and avoid cross-task races, subordinate contexts
#   (streams, task-groups, sessions) should be registered by calling
#   stack.enter_async_context(...), keeping enter/exit under the same stack/scope.
#
# ServerSlotSpec.open() will call stack.enter_async_context(open_uninitialized(stack)) and then
# call ClientSession.initialize() — this is the supported API.
# See related modules:
# - adgn/mcp/inproc_transport.py (in-proc FastMCP wiring)
# - mcp/shared/session.py (BaseSession: creates its own task group on enter)
# - mcp/server/lowlevel/server.py (Server.run uses AsyncExitStack + task group)
OpenFn = Callable[[AsyncExitStack], AbstractAsyncContextManager[ClientSession]]

# Module-level logger (AGENTS.md: declare at top)
logger = logging.getLogger(__name__)


@dataclass
class ServerSlot:
    """Realized slot (initialized session + initialization metadata)."""

    session: ClientSession
    init_result: InitializeResult


@dataclass
class ServerSlotSpec:
    """Recipe for opening a server slot (returns an uninitialized session).

    The registry key (mount name) is the authoritative server name; the spec does not
    need to carry a duplicate name field.
    """

    open_uninitialized: OpenFn
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Optional per-slot initialize timeout (seconds). None uses default; <= 0 disables timeout.
    init_timeout_secs: float | None = None

    async def open(self, stack: AsyncExitStack) -> ServerSlot:
        async with self.lock:
            logger.info("[SlotSpec] open: about to enter open_uninitialized; timeout=%s", self.init_timeout_secs)
            # open_uninitialized follows the canonical protocol and returns an
            # async context manager that yields an UNINITIALIZED ClientSession when
            # entered. Enter it via the provided AsyncExitStack so the same lifetime
            # boundary manages session teardown.
            sess = await stack.enter_async_context(self.open_uninitialized(stack))
            # Initialize timeout: configurable only via slot spec. When None or <= 0, no timeout is applied.
            try:
                if self.init_timeout_secs is None or self.init_timeout_secs <= 0:
                    logger.info("[SlotSpec] calling initialize (no timeout)")
                    init = await sess.initialize()
                else:
                    logger.info("[SlotSpec] calling initialize with timeout=%s", self.init_timeout_secs)
                    init = await asyncio.wait_for(sess.initialize(), timeout=float(self.init_timeout_secs))
                logger.info("[SlotSpec] initialize ok")
            except Exception as e:
                logger.exception("[SlotSpec] initialize failed: %s", e)
                raise
            return ServerSlot(session=sess, init_result=init)
