from __future__ import annotations

from fastmcp.client import Client
from fastmcp.server import FastMCP
import pytest


@pytest.mark.asyncio
async def test_server_slot_spec_open_initializes_once() -> None:
    app = FastMCP("demo")

    @app.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers"""
        return a + b

    client = Client(app)
    init = await client.initialize_result()
    assert isinstance(init.protocolVersion, str)
    tools = await client.list_tools()
    assert any(t.name == "add" for t in tools.tools or []), tools
