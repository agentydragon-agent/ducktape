from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import AsyncIterator, Callable, Tuple

import anyio
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.message import SessionMessage


@asynccontextmanager
async def fastmcp_inproc_client(
    make_server: Callable[[], FastMCP],
    *,
    read_timeout: timedelta | None = timedelta(seconds=15),
) -> AsyncIterator[
    Tuple[MemoryObjectReceiveStream[SessionMessage | Exception], MemoryObjectSendStream[SessionMessage]]
]:
    """Create an in-process MCP client transport to a FastMCP server using memory streams.

    This yields (client_read, client_write) suitable for mcp.client.session.ClientSession.

    Lifecycle:
    - Starts the FastMCP server loop on the server ends of the streams inside an anyio TaskGroup
    - Yields the client ends to the caller
    - On exit, closes the client write stream which allows the server loop to exit cleanly
    """
    # Create paired memory streams: client→server and server→client
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage](0)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage](0)

    # Map ends: client read/write vs server read/write
    client_read: MemoryObjectReceiveStream[SessionMessage | Exception] = s2c_recv  # server writes here
    client_write: MemoryObjectSendStream[SessionMessage] = c2s_send  # client writes here

    server_read: MemoryObjectReceiveStream[SessionMessage | Exception] = c2s_recv
    server_write: MemoryObjectSendStream[SessionMessage] = s2c_send

    # Build FastMCP server instance and its low-level runner
    mcp_server = make_server()
    # create_initialization_options contains serverInfo, capabilities, and optional instructions
    init_options = mcp_server._mcp_server.create_initialization_options()  # type: ignore[attr-defined]

    async with anyio.create_task_group() as tg:
        # Start server loop on the server ends
        tg.start_soon(mcp_server._mcp_server.run, server_read, server_write, init_options)  # type: ignore[attr-defined]
        try:
            yield (client_read, client_write)
        finally:
            # Close client write to allow server loop to finish
            await client_write.aclose()
            # Let the server task finish naturally when its read side closes


@asynccontextmanager
async def open_fastmcp_client_session(
    make_server: Callable[[], FastMCP],
    *,
    read_timeout: timedelta | None = timedelta(seconds=15),
) -> AsyncIterator[ClientSession]:
    """Higher-level helper: yields a ready ClientSession to an in-proc FastMCP server."""
    async with fastmcp_inproc_client(make_server, read_timeout=read_timeout) as (read, write):
        async with ClientSession(
            read_stream=read,
            write_stream=write,
            read_timeout_seconds=read_timeout,
        ) as client:
            await client.initialize()
            yield client
