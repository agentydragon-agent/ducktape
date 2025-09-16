from __future__ import annotations

import asyncio
import shutil

import pytest
from adgn_llm.mini_codex.mcp_manager import McpManager
from mcp.client.stdio import StdioServerParameters


@pytest.mark.asyncio
async def test_stdio_server_everything_lists_tools() -> None:
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
    spec = McpManager.slot_from_spec("everything", {"transport": "stdio", **params.model_dump()})

    async with McpManager({"everything": spec}) as mcp:
        tools = await mcp.list_tools()
        assert isinstance(tools, list) and tools, "No tools returned"
        assert any(t.get("type") == "function" for t in tools), "No function tools discovered"
