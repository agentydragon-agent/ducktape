from __future__ import annotations

import asyncio
import shutil

from fastmcp.mcp_config import StdioMCPServer
from mcp.client.stdio import StdioServerParameters
import pytest


@pytest.mark.asyncio
async def test_stdio_server_everything_lists_tools(make_compositor) -> None:
    """Smoke: spawn server-everything via stdio and list tools.

    Skips if `npx` not present or the help probe fails quickly.
    """
    if shutil.which("npx") is None:
        pytest.skip("npx not found in PATH; required for server-everything")

    # Preflight: ensure the CLI is installed/available
    try:
        proc = await asyncio.create_subprocess_exec(
            "npx",
            "--yes",
            "@modelcontextprotocol/server-everything",
            "stdio",
            "--help",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.wait(), timeout=20)
    except Exception as e:
        pytest.skip(f"preflight failed: {e}")
    if proc.returncode != 0:
        pytest.skip(f"server-everything stdio help failed (rc={proc.returncode})")

    params = StdioServerParameters(
        command="npx",
        args=["--yes", "@modelcontextprotocol/server-everything", "stdio"],
    )
    spec = StdioMCPServer(**params.model_dump())

    async with make_compositor({"everything": spec}) as (sess, comp):
        tools = await sess.list_tools()
        assert isinstance(tools, list), "tools is not a list"
        assert tools, "No tools returned"
        assert any(t.name.startswith("mcp__everything_") for t in tools), (
            "No tools under 'everything' server"
        )
