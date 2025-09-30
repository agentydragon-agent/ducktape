from __future__ import annotations

from contextlib import AsyncExitStack

from mcp.server.fastmcp import FastMCP
import pytest

from adgn.mcp.inproc_transport import make_inproc_slot_spec


@pytest.mark.asyncio
async def test_server_slot_spec_open_initializes_once() -> None:
    app = FastMCP("demo")

    @app.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers"""
        return a + b

    spec = make_inproc_slot_spec(app)

    async with AsyncExitStack() as stack:
        slot = await spec.open(stack)
        # Has a real initialization result
        assert isinstance(slot.init_result.protocolVersion, str)
        # The session is usable: list_tools sees our 'add'
        tools = await slot.session.list_tools()
        assert any(t.name == "add" for t in tools.tools or []), tools
