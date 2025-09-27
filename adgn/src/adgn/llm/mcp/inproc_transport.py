from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
import anyio

from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import NotificationOptions
from mcp.shared.memory import create_client_server_memory_streams

from adgn.llm.mcp.types import ServerSlotSpec


from typing import Awaitable as _Awaitable, Callable as _Callable
from mcp.shared.session import RequestResponder as _RequestResponder
from mcp import types as _types


def make_inproc_slot_spec(
    app: FastMCP,
    message_handler: _Callable[
        [
            _RequestResponder[_types.ServerRequest, _types.ClientResult]
            | _types.ServerNotification
            | Exception
        ],
        _Awaitable[None],
    ]
    | None = None,
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
            init_opts = app._mcp_server.create_initialization_options(  # type: ignore[attr-defined]
                notification_options=NotificationOptions(resources_changed=True)
            )
            tg.start_soon(
                app._mcp_server.run,  # type: ignore[attr-defined]
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
            try:
                yield sess
            finally:
                pass

        return _cm()

    return ServerSlotSpec(open_uninitialized=open_uninitialized)
