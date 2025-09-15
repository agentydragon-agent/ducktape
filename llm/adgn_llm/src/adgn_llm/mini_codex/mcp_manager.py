"""
MCP session manager — per-agent, FastMCP-first, DRY wiring.

- Per-agent isolation: each agent builds its own McpManager (its own sessions)
- One lifetime boundary: AsyncExitStack on the manager
- Transport-invariant wiring: ServerSlotSpec.open performs initialize exactly once; open_uninitialized returns an uninitialized ClientSession
"""

from __future__ import annotations
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Dict, Protocol, cast, Annotated, Union, AsyncContextManager
from pydantic import AnyUrl, BaseModel, Field
from typing import Literal
from adgn_llm.mcp.types import ServerSlot, ServerSlotSpec
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.resources.server import make_resources_server
import json
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
            # The ServerSlotSpec.open() follows the unified protocol: it enters the
            # opener's async context manager via the provided AsyncExitStack and
            # returns a fully-initialized ServerSlot. Rely on that contract here and
            # keep the logic simple and deterministic.
            slot = await spec.open(self._stack)
            self._realized[name] = slot
            return slot

    async def __aenter__(self) -> McpManager:  # type: ignore[name-defined]
        await self._stack.__aenter__()
        # Eagerly open all configured specs under the manager's task so all
        # subordinate contexts (task-groups, sessions) are entered in this same
        # task and will be cleanly exited in __aexit__ without cancel-scope races.
        async with self._lock:
            for name, spec in list(self._specs.items()):
                if name in self._realized:
                    continue
                self._realized[name] = await spec.open(self._stack)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # Gracefully shut down realized slots (servers/sessions) first so any
        # background tasks they spawned are awaited/cancelled under this
        # coroutine's cancel scope. This avoids the anyio "exit cancel scope in a
        # different task" error caused when tasks are created in a different
        # cancel scope than the one performing shutdown.
        async with self._lock:
            slots = list(self._realized.values())

        for slot in slots:
            # If the slot exposes an in-process server with a shutdown API, call it.
            srv = getattr(slot, "server", None)
            if srv is not None:
                try:
                    shutdown = getattr(srv, "shutdown", None)
                    if shutdown is not None:
                        if asyncio.iscoroutinefunction(shutdown):
                            await shutdown()
                        else:
                            # allow sync shutdown
                            shutdown()
                except Exception:
                    # Best-effort: do not fail shutdown because one server failed to stop
                    pass

            # If the slot exposes a client session, try to close it gracefully.
            sess = getattr(slot, "session", None)
            if sess is not None:
                try:
                    aclose = getattr(sess, "aclose", None)
                    if aclose is not None:
                        await aclose()
                except Exception:
                    pass

        # Finally, exit the AsyncExitStack to run remaining exit callbacks.
        await self._stack.__aexit__(exc_type, exc, tb)

    async def get_session(self, name: str) -> ClientSession:
        return (await self.ensure_open(name)).session

    async def list_tools(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in only or list(self._specs.keys()):
            sess = await self.get_session(name)
            res = await sess.list_tools()
            for t in res.tools or []:
                out.append(
                    {
                        "type": "function",
                        "name": f"mcp__{name}__{t.name}",
                        "description": t.description or "",
                        "parameters": t.inputSchema,
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
                        "uri": str(r.uri) if r.uri else None,
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
        # ClientSession.read_resource expects AnyUrl; inputs come as strings
        return await sess.read_resource(cast(AnyUrl, uri))

    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> Any:
        """Delegate tool call to the underlying ClientSession for the given server."""
        sess = await self.get_session(server)
        return await sess.call_tool(name=name, arguments=arguments)

    async def get_server_initialize(self, server: str) -> InitializeResult:
        """Return the InitializeResult for a server from the cached slot after opening."""
        slot = await self.ensure_open(server)
        return slot.init_result

    # ---- Typed Pydantic models for resources list/read ----
    class ResourceItem(BaseModel):
        server: str
        uri: str | None = None
        name: str | None = None
        description: str | None = None
        mime: str | None = None
        annotations: dict[str, Any] | None = None

    class ResourcesListRequest(BaseModel):
        server: str | None = None
        uri_prefix: str | None = None

    class ResourcesListResponse(BaseModel):
        resources: list["McpManager.ResourceItem"]

    class Window(BaseModel):
        start_offset: int
        max_bytes: int | None = None

    class ResourcePartText(BaseModel):
        kind: Literal["text"] = "text"
        mime: str | None = None
        text: str
        total_bytes: int
        bytes_returned: int

    class ResourcePartBase64(BaseModel):
        kind: Literal["base64"] = "base64"
        mime: str | None = None
        base64: str
        total_bytes: int
        bytes_returned: int

    ResourcePart = Annotated[
        Union["McpManager.ResourcePartText", "McpManager.ResourcePartBase64"],
        Field(discriminator="kind"),
    ]

    class ResourcesReadRequest(BaseModel):
        server: str
        uri: str
        start_offset: int = 0
        max_bytes: int | None = None

    class ResourcesReadResponse(BaseModel):
        window: "McpManager.Window"
        parts: list["McpManager.ResourcePart"]
        total_parts: int

    # ---- Resource helpers (typed) ----
    async def resources_list(self, req: "McpManager.ResourcesListRequest") -> "McpManager.ResourcesListResponse":
        items_raw = await self.list_resources(only=[req.server] if req.server else None)
        if req.uri_prefix:
            items_raw = [
                it for it in items_raw if isinstance(it.get("uri"), str) and it["uri"].startswith(req.uri_prefix)
            ]
        items = [self.ResourceItem(**it) for it in items_raw]
        return self.ResourcesListResponse(resources=items)

    async def resources_read(self, req: "McpManager.ResourcesReadRequest") -> "McpManager.ResourcesReadResponse":
        res = await self.read_resource(req.server, req.uri)
        contents = getattr(res, "contents", None) or []

        # typed window build
        class _Part(Protocol):
            mimeType: str | None
            text: str | None
            data: str | None

        remaining: int | None = req.max_bytes if isinstance(req.max_bytes, int) else None
        cursor = 0
        parts_out: list[McpManager.ResourcePart] = []
        for any_p in contents:
            p = cast(_Part, any_p)
            if isinstance(p.text, str):
                raw = p.text.encode("utf-8")
                total_len = len(raw)
                if remaining is None or remaining > 0:
                    start_in_part = max(0, req.start_offset - cursor)
                    take_cap = remaining if isinstance(remaining, int) else total_len
                    take = max(0, min(take_cap, total_len - start_in_part))
                    if take > 0:
                        chunk = raw[start_in_part : start_in_part + take]
                        parts_out.append(
                            self.ResourcePartText(
                                mime=p.mimeType,
                                text=chunk.decode("utf-8", errors="replace"),
                                total_bytes=total_len,
                                bytes_returned=take,
                            )
                        )
                        if remaining is not None:
                            remaining -= take
            elif isinstance(p.data, str):
                base = p.data
                total_len = len(base)
                if remaining is None or remaining > 0:
                    start_in_part = max(0, req.start_offset - cursor)
                    take_cap = remaining if isinstance(remaining, int) else total_len
                    take = max(0, min(take_cap, total_len - start_in_part))
                    if take > 0:
                        parts_out.append(
                            self.ResourcePartBase64(
                                mime=p.mimeType,
                                base64=base[start_in_part : start_in_part + take],
                                total_bytes=total_len,
                                bytes_returned=take,
                            )
                        )
                        if remaining is not None:
                            remaining -= take
            cursor += len(p.text.encode("utf-8")) if isinstance(p.text, str) else len(p.data or "")
            if remaining is not None and remaining <= 0:
                break
        return self.ResourcesReadResponse(
            window=self.Window(start_offset=req.start_offset, max_bytes=req.max_bytes),
            parts=parts_out,
            total_parts=len(contents),
        )

    async def resources_list_json(self, server_filter: str | None, uri_prefix: str | None) -> str:
        resp = await self.resources_list(self.ResourcesListRequest(server=server_filter, uri_prefix=uri_prefix))
        return json.dumps(resp.model_dump(exclude_none=True), ensure_ascii=False)

    @staticmethod
    def _build_resource_window(contents: list[Any], start_offset: int, max_bytes: int | None) -> dict[str, Any]:
        class _ResourcePart(Protocol):
            mimeType: str | None
            text: str | None
            data: str | None

        remaining: int | None = max_bytes if isinstance(max_bytes, int) else None
        cursor = 0
        parts_out: list[dict[str, Any]] = []
        for part_any in contents or []:
            p = cast(_ResourcePart, part_any)
            if isinstance(p.text, str):
                raw = p.text.encode("utf-8")
                total_len = len(raw)
                if remaining is None or remaining > 0:
                    start_in_part = max(0, start_offset - cursor)
                    take_cap = remaining if isinstance(remaining, int) else total_len
                    take = max(0, min(take_cap, total_len - start_in_part))
                    if take > 0:
                        chunk = raw[start_in_part : start_in_part + take]
                        parts_out.append(
                            {
                                "mime": p.mimeType,
                                "text": chunk.decode("utf-8", errors="replace"),
                                "total_bytes": total_len,
                                "bytes_returned": take,
                            }
                        )
                        if remaining is not None:
                            remaining -= take
            elif isinstance(p.data, str):
                base = p.data
                total_len = len(base)
                if remaining is None or remaining > 0:
                    start_in_part = max(0, start_offset - cursor)
                    take_cap = remaining if isinstance(remaining, int) else total_len
                    take = max(0, min(take_cap, total_len - start_in_part))
                    if take > 0:
                        parts_out.append(
                            {
                                "mime": p.mimeType,
                                "base64": base[start_in_part : start_in_part + take],
                                "total_bytes": total_len,
                                "bytes_returned": take,
                            }
                        )
                        if remaining is not None:
                            remaining -= take
            cursor += len(p.text.encode("utf-8")) if isinstance(p.text, str) else len(p.data or "")
            if remaining is not None and remaining <= 0:
                break
        return {
            "window": {"start_offset": start_offset, "max_bytes": max_bytes},
            "parts": parts_out,
            "total_parts": len(contents or []),
        }

    async def resources_read_json(self, server: str, uri: str, start_offset: int, max_bytes: int | None) -> str:
        """Return JSON string for a resource read window payload (server, uri)."""
        res = await self.read_resource(server, uri)
        contents = getattr(res, "contents", None) or []
        payload = self._build_resource_window(contents, start_offset, max_bytes)
        return json.dumps(payload, ensure_ascii=False)

    @property
    def server_names(self) -> list[str]:
        """Configured server names (public API)."""
        return list(self._specs.keys())

    async def render_banner(self) -> str:
        """Render a merged MCP servers/resources banner for instruction headers.

        Format:
        FYI: MCP servers/resources:
        - server=<name>
          resources: [first 5 URIs] (+N more; list via mcp__resources__list)
          <name server desc>
          ... initialize.instructions ...
          </name server desc>
        """
        # Group resources by server
        resources = await self.list_resources()
        by_server: dict[str, list[str]] = {}
        for it in resources:
            server = it.get("server")
            uri = it.get("uri")
            if isinstance(server, str) and isinstance(uri, str):
                by_server.setdefault(server, []).append(uri)
        # Build per-server entries
        lines: list[str] = []
        for sname in self.server_names:
            uris = by_server.get(sname, [])
            sample = uris[:5]
            more = max(0, len(uris) - len(sample))
            init_res = await self.get_server_initialize(sname)
            desc = init_res.instructions
            entry = f"server={sname}\n  resources: {sample}"
            if more:
                entry += f" (+{more} more; list via mcp__resources__list)"
            if isinstance(desc, str) and desc:
                entry += f"\n  <{sname} server desc>\n{desc}\n  </{sname} server desc>"
            lines.append(entry)
        if not lines:
            return ""
        return "FYI: MCP servers/resources:\n- " + "\n- ".join(lines)

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

            def open_uninitialized(
                stack: AsyncExitStack,
            ) -> AsyncContextManager[ClientSession]:
                """Return an async context manager that yields an UNINITIALIZED ClientSession.

                This matches the canonical OpenFn protocol: the returned async context
                manager will be entered by the caller's AsyncExitStack so teardown runs
                under the same lifetime boundary.
                """

                @asynccontextmanager
                async def _ctx():
                    read, write = await stack.enter_async_context(stdio_client(params))
                    sess = ClientSession(read_stream=read, write_stream=write)
                    await stack.enter_async_context(sess)
                    try:
                        yield sess
                    finally:
                        return

                return _ctx()

            return ServerSlotSpec(open_uninitialized=open_uninitialized)

        if transport == "sse":
            url_val = spec.get("url")
            if not isinstance(url_val, str) or not url_val:
                raise ValueError("SSE transport requires a non-empty 'url' string in spec")
            headers = spec.get("headers")
            timeout = spec.get("timeout", 5)
            sse_read_timeout = spec.get("sse_read_timeout", 60 * 5)

            def open_uninitialized(
                stack: AsyncExitStack,
            ) -> AsyncContextManager[ClientSession]:
                """Return an async context manager that yields an UNINITIALIZED ClientSession for SSE transport."""

                @asynccontextmanager
                async def _ctx():
                    read, write = await stack.enter_async_context(
                        sse_client(
                            url=url_val,
                            headers=headers,
                            timeout=timeout,
                            sse_read_timeout=sse_read_timeout,
                        )
                    )
                    sess = ClientSession(read_stream=read, write_stream=write)
                    await stack.enter_async_context(sess)
                    try:
                        yield sess
                    finally:
                        return

                return _ctx()

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
