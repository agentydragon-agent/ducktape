"""
MCP session manager — per-agent, FastMCP-first, DRY wiring.

- Per-agent isolation: each agent builds its own McpManager (its own sessions)
- One lifetime boundary: AsyncExitStack on the manager
- Transport-invariant wiring: ServerSlotSpec.open performs initialize exactly once; open_uninitialized returns an uninitialized ClientSession
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict
from adgn_llm.mcp.types import ServerSlot, ServerSlotSpec
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.resources.server import make_resources_server

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.types import InitializeResult

# Shared MCP naming helpers/constants
MCP_NAMESPACE_PREFIX = "mcp__"


def build_mcp_function(server: str, tool: str) -> str:
    return f"{MCP_NAMESPACE_PREFIX}{server}__{tool}"


def parse_mcp_function(namespaced: str) -> tuple[str, str]:
    if not namespaced.startswith(MCP_NAMESPACE_PREFIX):
        raise ValueError(f"Not an MCP tool name: {namespaced}")
    remainder = namespaced[len(MCP_NAMESPACE_PREFIX) :]
    if "__" not in remainder:
        raise ValueError(f"Invalid MCP tool name: {namespaced}")
    server, tool = remainder.split("__", 1)
    return server, tool


# ---- Legacy in-proc adapter removed (use FastMCP in-proc memory transport) ----


class McpManager:
    """Per-agent bag of MCP sessions; lazy-open; one lifetime (AsyncExitStack)."""

    def __init__(self, specs: Dict[str, ServerSlotSpec]):
        # Always include the resources shim server; reserve the name 'resources'
        self._specs = dict(specs)
        assert "resources" not in self._specs, (
            "'resources' server name is reserved; McpManager injects it automatically"
        )
        resources_server = make_resources_server(self, "resources")
        self._specs["resources"] = make_inproc_slot_spec(resources_server)

        self._realized: Dict[str, ServerSlot] = {}
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()

    async def ensure_open(self, name: str) -> ServerSlot:
        async with self._lock:
            slot = self._realized.get(name)
            if slot is not None:
                return slot
            spec = self._specs.get(name)
            if spec is None:
                raise KeyError(f"Unknown MCP server slot: {name}")
            slot = await spec.open(self._stack)
            self._realized[name] = slot
            return slot

    async def __aenter__(self) -> McpManager:  # type: ignore[name-defined]
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stack.__aexit__(exc_type, exc, tb)

    async def get_session(self, name: str) -> ClientSession:
        return (await self.ensure_open(name)).session

    async def list_tools(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        def _strip_ctx(schema: Any) -> Any:
            if not isinstance(schema, dict):
                return schema
            props = schema.get("properties")
            if isinstance(props, dict) and "ctx" in props:
                props = dict(props)
                props.pop("ctx", None)
                schema = dict(schema)
                schema["properties"] = props
            req = schema.get("required")
            if isinstance(req, list) and "ctx" in req:
                schema = dict(schema)
                schema["required"] = [r for r in req if r != "ctx"]
            return schema

        out: list[dict[str, Any]] = []
        for name in only or list(self._specs.keys()):
            sess = await self.get_session(name)
            res = await sess.list_tools()
            for t in res.tools or []:
                schema = _strip_ctx(t.inputSchema or {"type": "object", "properties": {}})
                out.append(
                    {
                        "type": "function",
                        "name": f"mcp__{name}__{t.name}",
                        "description": t.description or "",
                        "parameters": schema,
                    },
                )
        return out

    async def list_resources(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        """Return a fresh view of resources across servers.

        Each item: {server, uri, name?, description?, mime?, annotations?}
        """
        items: list[dict[str, Any]] = []
        for server_name in only or list(self._specs.keys()):
            sess = await self.get_session(server_name)
            res = await sess.list_resources()
            for r in res.resources or []:
                items.append(
                    {
                        "server": server_name,
                        "uri": str(r.uri) if r.uri is not None else None,
                        "name": r.name,
                        "description": r.description,
                        "mime": r.mimeType,
                        "annotations": r.annotations,
                    }
                )
        return items

    async def read_resource(self, server: str, uri: str) -> Any:
        """Thin wrapper around ClientSession.read_resource(uri)."""
        sess = await self.get_session(server)
        return await sess.read_resource(uri)

    async def get_server_initialize(self, server: str) -> InitializeResult:
        """Return the InitializeResult for a server from the cached slot after opening."""
        slot = await self.ensure_open(server)
        return slot.init_result

    @property
    def server_names(self) -> list[str]:
        """Configured server names (public API)."""
        return list(self._specs.keys())

    @staticmethod
    def slot_from_spec(name: str, spec: Any) -> "ServerSlotSpec":
        """Create a ServerSlotSpec from a transport spec.

        Accepted shapes:
        - Dict with explicit "transport": "stdio" | "sse" | "http" parsed via the corresponding Pydantic params
        The returned spec's opener yields an UNINITIALIZED ClientSession; initialize is performed by ServerSlotSpec.open.
        """
        if not isinstance(spec, dict):
            raise TypeError(f"Unsupported MCP server spec type for {name!r}: {type(spec)!r}")

        transport = spec.get("transport")
        if transport is None and any(k in spec for k in ("command", "args", "env")):
            transport = "stdio"

        if transport == "stdio":
            params = StdioServerParameters.model_validate(spec)

            async def open_uninitialized(stack: AsyncExitStack) -> ClientSession:
                read, write = await stack.enter_async_context(stdio_client(params))
                sess = ClientSession(read_stream=read, write_stream=write)
                await stack.enter_async_context(sess)
                return sess

            return ServerSlotSpec(open_uninitialized=open_uninitialized)

        if transport == "sse":
            url = spec.get("url")
            headers = spec.get("headers")
            timeout = spec.get("timeout", 5)
            sse_read_timeout = spec.get("sse_read_timeout", 60 * 5)

            async def open_uninitialized(stack: AsyncExitStack) -> ClientSession:
                read, write = await stack.enter_async_context(
                    sse_client(url=url, headers=headers, timeout=timeout, sse_read_timeout=sse_read_timeout)
                )
                sess = ClientSession(read_stream=read, write_stream=write)
                await stack.enter_async_context(sess)
                return sess

            return ServerSlotSpec(open_uninitialized=open_uninitialized)

        # HTTP transport not supported in this environment version; add when needed.

        raise ValueError(f"Unsupported or missing transport in spec for {name!r} (keys={list(spec.keys())!r})")

    @staticmethod
    # TODO(mpokorny): If needed later, add an 'inproc' transport that loads a dotted factory path
    # to create a FastMCP server in-proc from JSON config. For now, prefer explicit wiring in code.
    def slots_from_specs(specs: Dict[str, Any]) -> Dict[str, "ServerSlotSpec"]:
        """Parse a mapping of name→transport spec into ServerSlotSpec entries.

        Each entry yields an UNINITIALIZED ClientSession when opened; initialization
        is performed exactly once in ServerSlotSpec.open().
        """
        return {name: McpManager.slot_from_spec(name, spec) for name, spec in (specs or {}).items()}

    def resolve_function(self, namespaced: str) -> tuple[str, str]:
        # Back-compat: instance method delegating to parse helper
        return parse_mcp_function(namespaced)
