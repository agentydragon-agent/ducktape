from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Mapping

import pytest

from adgn_llm.mini_codex.mcp_manager import McpManager


def test_stdio_server_list_tools() -> None:
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

    servers: dict[str, Mapping[str, Any]] = {
        "everything": {
            "command": "npx",
            "args": ["@modelcontextprotocol/server-everything", "stdio"],
        }
    }
    mgr = McpManager.from_servers(servers)
    try:
        tools = mgr.list_tools()
        assert isinstance(tools, list)
        assert any(t.get("type") == "function" for t in tools)
    finally:
        mgr.close()


def test_local_inprocess_server() -> None:
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
    mgr = McpManager.from_servers({}, local=local)
    try:
        tools = mgr.list_tools()
        names = [t["function"]["name"] for t in tools]
        assert "mcp:local.echo" in names
        # Call the local tool
        out = mgr.call_tool("mcp:local.echo", {"msg": "hi"})
        assert out.get("exit") == 0
        assert out.get("json") == {"echo": {"msg": "hi"}}
    finally:
        mgr.close()
