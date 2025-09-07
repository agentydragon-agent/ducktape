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
    name: str
    open_fn: OpenFn
    session: ClientSession | None = None
    init_result: InitializeResult | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def open(self, stack: AsyncExitStack) -> ClientSession:
        async with self.lock:
            if self.session is not None:
                return self.session
            sess = await self.open_fn(stack)
            # Initialize once and cache InitializeResult for later description access
            init_res: InitializeResult = await sess.initialize()
            self.init_result = init_res
            self.session = sess
            return sess


class McpManager:
    """Per-agent bag of MCP sessions; lazy-open; one lifetime (AsyncExitStack)."""

    def __init__(self, slots: Dict[str, ServerSlot]):
        self._slots = slots
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> McpManager:  # type: ignore[name-defined]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stack.aclose()

    async def get_session(self, name: str) -> ClientSession:
        slot = self._slots[name]
        await slot.open(self._stack)
        return slot.session  # type: ignore[return-value]

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
        for name in only or list(self._slots.keys()):
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
        for server_name in only or list(self._slots.keys()):
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
        """Return the cached InitializeResult for a server (no re-initialize)."""
        # Ensure session is opened (and thus initialized once)
        await self.get_session(server)
        slot = self._slots[server]
        if slot.init_result is None:
            raise RuntimeError(f"InitializeResult missing for server {server!r}")
        return slot.init_result

    @staticmethod
    def slot_from_spec(name: str, spec: Any) -> "ServerSlot":
        """Create a ServerSlot from a spec — strict, zero-guessing.

        Accepted shapes:
        - Dict with explicit "transport": "stdio" | "sse" | "http" parsed via the corresponding Pydantic params
        """
        # Explicit dict: choose transport; default to stdio when omitted but stdio-like keys exist
        # TODO(mpokorny): This dispatch duplicates config parsing; prefer delegating to FastMCP's
        # JSON config helper when available, or centralize transport selection in one place.
        if isinstance(spec, dict):
            transport = spec.get("transport")
            if transport is None and any(k in spec for k in ("command", "args", "env")):
                transport = "stdio"
            if transport == "stdio":
                from mcp.client.stdio import (  # type: ignore  # noqa: PLC0415
                    StdioServerParameters,
                    stdio_client,
                )

                params = StdioServerParameters.model_validate(spec)
                return ServerSlot(name=name, open_fn=session_opener(lambda: stdio_client(params)))
            if transport == "sse":
                from mcp.client.sse import SseClientParams, sse_client  # type: ignore  # noqa: PLC0415

                params = SseClientParams.model_validate(spec)
                return ServerSlot(name=name, open_fn=session_opener(lambda: sse_client(params)))
            if transport == "http":
                from mcp.client.streamable_http import (  # type: ignore  # noqa: PLC0415
                    HttpClientParams,
                    http_client,
                )

                params = HttpClientParams.model_validate(spec)
                return ServerSlot(name=name, open_fn=session_opener(lambda: http_client(params)))
            raise ValueError(f"Unsupported or missing transport in spec for {name!r} (keys={list(spec.keys())!r})")

        raise TypeError(f"Unsupported MCP server spec type for {name!r}: {type(spec)!r}")

    @staticmethod
    # TODO(mpokorny): If needed later, add an 'inproc' transport that loads a dotted factory path
    # to create a FastMCP server in-proc from JSON config. For now, prefer explicit wiring in code.
    def slots_from_specs(specs: Dict[str, Any]) -> Dict[str, "ServerSlot"]:
        return {name: McpManager.slot_from_spec(name, spec) for name, spec in (specs or {}).items()}

    def resolve_function(self, namespaced: str) -> tuple[str, str]:
        if not namespaced.startswith("mcp__"):
            raise ValueError(f"Not an MCP tool name: {namespaced}")
        remainder = namespaced[len("mcp__") :]
        if "__" not in remainder:
            raise ValueError(f"Invalid MCP tool name: {namespaced}")
        server, tool = remainder.split("__", 1)
        return server, tool
