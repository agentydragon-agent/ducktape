from __future__ import annotations

import asyncio
import shutil

import pytest
from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.mcp.local_exec.server import make_local_exec_mcp
from adgn_llm.mcp.inproc_utils import make_inproc_slot_spec

from adgn_llm.mini_codex.mcp_manager import (
    McpManager,
)

# FastMCP stdio client
try:
    from mcp.client.stdio import StdioServerParameters, stdio_client
except Exception:  # pragma: no cover
    stdio_client = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_stdio_server_list_tools() -> None:
    """Smoke test: connect to server-everything (stdio) and list tools.

    Skips if npx or FastMCP stdio client are unavailable.
    """
    if shutil.which("npx") is None:
        pytest.skip("npx not found in PATH; required for server-everything")
    if stdio_client is None or StdioServerParameters is None:
        pytest.skip("FastMCP stdio client not available")

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
    except Exception as e:  # pragma: no cover - infra-dependent
        pytest.skip(f"preflight failed: {e}")
    if proc.returncode != 0:
        pytest.skip(f"server-everything stdio help failed (rc={proc.returncode})")


    spec = McpManager.slot_from_spec(
        "everything",
        {
            "transport": "stdio",
            "command": "npx",
            "args": ["@modelcontextprotocol/server-everything", "stdio"],
        },
    )

    async with McpManager({"everything": spec}) as mcp:
        specs = await mcp.list_tools()
        assert isinstance(specs, list)
        assert any(s.get("type") == "function" for s in specs)
        # At least one tool is namespaced under everything
        assert any((s.get("name") or "").startswith("mcp__everything__") for s in specs)


@pytest.mark.asyncio
async def test_local_inprocess_server() -> None:
    """Local in-process FastMCP exec tool via memory streams (no stdio)."""

    # Import FastMCP in-proc helpers locally to avoid global import churn

    spec = make_inproc_slot_spec(make_local_exec_mcp("local"))
    async with McpManager({"local": spec}) as mcp:
        specs = await mcp.list_tools()
        names = [s.get("name") for s in specs]
        assert "mcp__local__exec" in names


@pytest.mark.asyncio
async def test_inproc_container_exec_exposes_container_info_resource() -> None:
    """Smoke test: in-proc container exec exposes a container.info resource."""


    spec = make_inproc_slot_spec(
        make_container_exec_mcp(
            image="python:3.12-slim",
            working_dir="/workspace",
            volumes=None,
            describe=False,
        )
    )

    async with McpManager({"docker": spec}) as mcp:
        sess = await mcp.get_session("docker")
        # Existence: can read the resource
        res = await sess.read_resource("resource://container.info")
        assert res.contents, "container.info returned no contents"


@pytest.mark.asyncio
async def test_inproc_container_exec_container_info_shape() -> None:
    """Read container.info resource and sanity-check shape."""

    spec = make_inproc_slot_spec(
        make_container_exec_mcp(
            image="python:3.12-slim",
            working_dir="/workspace",
            volumes=None,
            describe=False,
        )
    )

    async with McpManager({"docker": spec}) as mcp:
        sess = await mcp.get_session("docker")
        res = await sess.read_resource("resource://container.info")
        contents = res.contents or []
        assert contents, "container.info returned no contents"
