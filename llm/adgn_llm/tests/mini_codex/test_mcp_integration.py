from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any

import openai
import pytest
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.local_exec_server import LocalExecServer


@pytest.mark.asyncio
async def test_stdio_server_list_tools() -> None:
    """Smoke test: connect to a known stdio MCP server via npx and list tools.

    Requires Node/npm available. Skip if not installed.
    """
    if shutil.which("npx") is None:
        pytest.skip("npx not found in PATH; required for server-everything")

    # Preflight: verify server-everything can start (help) quickly; skip if not
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

    tools_map: dict[str, Any] = {
        "everything": {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-everything", "stdio"],
        },
    }
    agent = await MiniCodex.start(
        model=os.getenv("OPENAI_MODEL", "o4-mini"),
        tools=tools_map,
        client=openai.OpenAI(),
    )
    try:
        specs = agent.tools()
        assert isinstance(specs, list)
        assert any(s.get("type") == "function" for s in specs)
    finally:
        await agent.close()


@pytest.mark.asyncio
async def test_local_inprocess_server() -> None:
    """Local in-process MCP-like tools without stdio process."""

    def echo_handler(args: dict[str, Any]) -> dict[str, Any]:
        return {"echo": args}

    agent = await MiniCodex.start(
        model=os.getenv("OPENAI_MODEL", "o4-mini"),
        tools={"local": LocalExecServer("local")},
        client=openai.OpenAI(),
    )
    try:
        specs = agent.tools()
        names = [s.get("name") for s in specs]
        assert "mcp__local__exec" in names
    finally:
        await agent.close()
