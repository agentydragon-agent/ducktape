from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Mapping

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
        cp = subprocess.run(
            ["npx", "--yes", "@modelcontextprotocol/server-everything", "stdio", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
    except Exception as e:
        pytest.skip(f"preflight failed: {e}")
    if cp.returncode != 0:
        pytest.skip(f"server-everything stdio help failed (rc={cp.returncode})")

    tools_map: dict[str, Any] = {
        "everything": {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-everything", "stdio"],
        }
    }
    agent = await MiniCodex.start(model=os.getenv("OPENAI_MODEL", "o4-mini"), tools=tools_map)
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

    local = {
        "local": {
            "echo": (
                "Echoes arguments",
                {"type": "object", "properties": {"msg": {"type": "string"}}},
                echo_handler,
            )
        }
    }
    agent = await MiniCodex.start(
        model=os.getenv("OPENAI_MODEL", "o4-mini"),
        tools={"local": LocalExecServer("local")},
    )
    try:
        specs = agent.tools()
        names = [s.get("name") for s in specs]
        assert "mcp__local__exec" in names
    finally:
        await agent.close()
