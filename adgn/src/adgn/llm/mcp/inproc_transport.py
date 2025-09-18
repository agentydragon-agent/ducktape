from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, suppress

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

            # Start the FastMCP server in an asyncio Task and register a cleanup
            # callback on the manager's stack to cancel and await it on exit.
            server_task = asyncio.create_task(
                app._mcp_server.run(  # type: ignore[attr-defined]
                    server_read,
                    server_write,
                    app._mcp_server.create_initialization_options(),  # type: ignore[attr-defined]
                )
            )

            async def _cancel_server_task(task: asyncio.Task):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

            stack.push_async_callback(_cancel_server_task, server_task)

            # Enter the client session via the manager's AsyncExitStack so enter/exit
            # occur within the same task/cancel scope when the stack unwinds.
            sess = await stack.enter_async_context(
                ClientSession(read_stream=client_read, write_stream=client_write)
            )
            try:
                yield sess
            finally:
                pass

        return _cm()

    return ServerSlotSpec(open_uninitialized=open_uninitialized)
