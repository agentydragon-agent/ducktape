from __future__ import annotations

from contextlib import AsyncExitStack

import anyio
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_client_server_memory_streams

from adgn_llm.mini_codex.mcp_manager import ServerSlotSpec


def make_inproc_slot_spec(app: FastMCP) -> ServerSlotSpec:
    """Create a ServerSlotSpec for an in-proc FastMCP server.

    The McpManager dict key is the authoritative server name; this spec does not
    take a name argument. Its opener yields an UNINITIALIZED ClientSession that
    speaks JSON-RPC over in-memory message streams. ServerSlotSpec.open() is
    responsible for calling initialize() exactly once and caching the real
    InitializeResult.
    """

    async def open_uninitialized(stack: AsyncExitStack) -> ClientSession:
        (client_read, client_write), (server_read, server_write) = await stack.enter_async_context(
            create_client_server_memory_streams()
        )
        # Start FastMCP low-level server in a task group matching SDK teardown pattern.
        # Note: "open_uninitialized" refers to the CLIENT session; the server must be
        # started with its initialization options to accept the client's initialize() call.
        # This mirrors mcp.shared.memory.create_connected_server_and_client_session.
        tg = await stack.enter_async_context(anyio.create_task_group())
        tg.start_soon(
            lambda: app._mcp_server.run(  # type: ignore[attr-defined]
                server_read,
                server_write,
                app._mcp_server.create_initialization_options(),  # type: ignore[attr-defined]
            )
        )
        # Client session remains UNINITIALIZED here
        sess = ClientSession(read_stream=client_read, write_stream=client_write)
        await stack.enter_async_context(sess)
        return sess

    return ServerSlotSpec(open_uninitialized=open_uninitialized)
