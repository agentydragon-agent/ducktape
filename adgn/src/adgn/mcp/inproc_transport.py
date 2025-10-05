from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
import logging
from typing import cast

import anyio

from adgn.mcp.types import ServerSlotSpec
from mcp.client.session import ClientSession, MessageHandlerFnT
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import NotificationOptions, Server
from mcp.shared.memory import create_client_server_memory_streams

logger = logging.getLogger(__name__)


def make_inproc_slot_spec(
    app: FastMCP,
    message_handler: MessageHandlerFnT | None = None,
    *,
    init_timeout_secs: float | None = None,
) -> ServerSlotSpec:
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

            # Run the FastMCP server under an AnyIO task group that is itself
            # managed by the same AsyncExitStack. This guarantees that server
            # startup and shutdown occur within the same cancel scope as the
            # client session, avoiding cross-task scope mismatches.
            tg = await stack.enter_async_context(anyio.create_task_group())
            low_server = cast(Server, getattr(app, "_mcp_server"))
            name = getattr(low_server, "name", "<unknown>")
            init_opts = low_server.create_initialization_options(
                notification_options=NotificationOptions(resources_changed=True)
            )
            # Instrumentation: surface when the low-level server run loop starts
            logger.info("[Inproc] starting server.run: %s", name)
            try:
                print(f"[Inproc] starting server.run: {name}")
            except Exception:
                pass
            tg.start_soon(
                low_server.run,
                server_read,
                server_write,
                init_opts,
            )
            # Now enter the client session. On teardown, the client session will
            # close before the server task group, signaling end-of-stream and
            # allowing the server read loop to exit cleanly.
            sess = await stack.enter_async_context(
                ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    message_handler=message_handler,
                )
            )
            # Instrumentation: client session successfully created and entered
            logger.info("[Inproc] client session entered: %s", name)
            try:
                print(f"[Inproc] client session entered: {name}")
            except Exception:
                pass
            # Yield the uninitialized session; teardown is fully handled by the
            # AsyncExitStack context managers above (no-op finally).
            yield sess

        return _cm()

    return ServerSlotSpec(
        open_uninitialized=open_uninitialized, init_timeout_secs=init_timeout_secs
    )
