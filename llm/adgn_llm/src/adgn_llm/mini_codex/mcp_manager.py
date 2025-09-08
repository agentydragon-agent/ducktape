"""
MCP session manager — per-agent, FastMCP-first, DRY wiring.

- Per-agent isolation: each agent builds its own McpManager (its own sessions)
- One lifetime boundary: AsyncExitStack on the manager
- DRY transport wiring: one session_opener to turn any client CM into a ready ClientSession
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Tuple

from mcp.client.session import ClientSession
from mcp.types import InitializeResult

# ---- DRY: open a ready session under a single ExitStack ----
OpenFn = Callable[[AsyncExitStack], Awaitable[ClientSession]]


def session_opener(
    cm_builder: Callable[[], AbstractAsyncContextManager[Tuple[Any, Any]]],
) -> OpenFn:
    async def open_with(stack: AsyncExitStack) -> ClientSession:
        read, write = await stack.enter_async_context(cm_builder())
        sess = ClientSession(read, write)
        await stack.enter_async_context(sess)
        await sess.initialize()
        return sess

    return open_with


# ---- Legacy in-proc adapter removed (use FastMCP in-proc memory transport) ----


@dataclass
class ServerSlot:
    """Realized slot (initialized session + initialization metadata)."""

    session: ClientSession
    init_result: InitializeResult


@dataclass
class ServerSlotSpec:
    """Recipe for opening a server slot (returns an uninitialized session).

    The McpManager dict key is the authoritative server name; the spec does not
    need to carry a duplicate name field.
    """

    open_uninitialized: OpenFn
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def open(self, stack: AsyncExitStack) -> ServerSlot:
        async with self.lock:
            sess = await self.open_uninitialized(stack)
            init = await sess.initialize()
            return ServerSlot(session=sess, init_result=init)


class McpManager:
    """Per-agent bag of MCP sessions; lazy-open; one lifetime (AsyncExitStack)."""

    def __init__(self, specs: Dict[str, ServerSlotSpec]):
        self._specs = specs
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
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stack.aclose()

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
        """Return the InitializeResult for a server without forcing re-initialize.

        Some transports (e.g., in-memory helpers) already perform initialization
        inside the client/session context. If we don't have a cached result, we
        synthesize a minimal placeholder after ensuring the session is open.
        """
        slot = await self.ensure_open(server)
        return slot.init_result

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
            from mcp.client.stdio import (  # noqa: PLC0415
                StdioServerParameters,
                stdio_client,
            )

            params = StdioServerParameters.model_validate(spec)

            async def open_uninitialized(stack: AsyncExitStack) -> ClientSession:
                read, write = await stack.enter_async_context(stdio_client(params))
                from mcp.client.session import ClientSession as _CS  # local import

                sess = _CS(read_stream=read, write_stream=write)
                await stack.enter_async_context(sess)
                return sess

            return ServerSlotSpec(open_uninitialized=open_uninitialized)

        if transport == "sse":
            from mcp.client.sse import SseClientParams, sse_client  # noqa: PLC0415

            params = SseClientParams.model_validate(spec)

            async def open_uninitialized(stack: AsyncExitStack) -> ClientSession:
                read, write = await stack.enter_async_context(sse_client(params))
                from mcp.client.session import ClientSession as _CS

                sess = _CS(read_stream=read, write_stream=write)
                await stack.enter_async_context(sess)
                return sess

            return ServerSlotSpec(open_uninitialized=open_uninitialized)

        if transport == "http":
            from mcp.client.streamable_http import (  # noqa: PLC0415
                HttpClientParams,
                http_client,
            )

            params = HttpClientParams.model_validate(spec)

            async def open_uninitialized(stack: AsyncExitStack) -> ClientSession:
                read, write = await stack.enter_async_context(http_client(params))
                from mcp.client.session import ClientSession as _CS

                sess = _CS(read_stream=read, write_stream=write)
                await stack.enter_async_context(sess)
                return sess

            return ServerSlotSpec(open_uninitialized=open_uninitialized)

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
        if not namespaced.startswith("mcp__"):
            raise ValueError(f"Not an MCP tool name: {namespaced}")
        remainder = namespaced[len("mcp__") :]
        if "__" not in remainder:
            raise ValueError(f"Invalid MCP tool name: {namespaced}")
        server, tool = remainder.split("__", 1)
        return server, tool
