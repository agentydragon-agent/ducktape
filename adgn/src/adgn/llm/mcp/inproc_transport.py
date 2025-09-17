from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

import anyio
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_client_server_memory_streams

from adgn.llm.mcp.types import ServerSlotSpec


def make_inproc_slot_spec(app: FastMCP) -> ServerSlotSpec:
    """Create a ServerSlotSpec for an in-proc FastMCP server.

    The opener yields an UNINITIALIZED ClientSession as an async context manager.
    ServerSlotSpec.open() is responsible for calling initialize() exactly once and
    caching the real InitializeResult.
    """

    def open_uninitialized(stack: AsyncExitStack):
        @asynccontextmanager
        async def _cm():
            # create paired in-memory streams for client/server
            (
                (client_read, client_write),
                (server_read, server_write),
            ) = await stack.enter_async_context(
                create_client_server_memory_streams(),
            )

            # Create and register a task group under the manager stack so both
            # server and session tasks share the same cancel scope.
            tg = await stack.enter_async_context(anyio.create_task_group())
            tg.start_soon(
                app._mcp_server.run,  # type: ignore[attr-defined]
                server_read,
                server_write,
                app._mcp_server.create_initialization_options(),  # type: ignore[attr-defined]
            )

            # Enter the client session under the same stack so its task group and
            # the server task are siblings under the manager-owned task group.
            sess = await stack.enter_async_context(
                ClientSession(read_stream=client_read, write_stream=client_write),
            )

            try:
                yield sess
            finally:
                # session and task group cleanup will be handled by AsyncExitStack
                pass

        return _cm()

    return ServerSlotSpec(open_uninitialized=open_uninitialized)
