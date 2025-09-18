"""MCP session manager — per-agent, FastMCP-first, DRY wiring.

- Per-agent isolation: each agent builds its own McpManager (its own sessions)
- One lifetime boundary: AsyncExitStack on the manager
- Transport-invariant wiring: ServerSlotSpec.open performs initialize exactly once; open_uninitialized returns an uninitialized ClientSession
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
import json
from typing import Annotated, Any, Literal, Protocol, Union, cast

from mcp import types as mcp_types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import InitializeResult
from pydantic import AnyUrl, BaseModel, Field, TypeAdapter

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.resources.server import make_resources_server
from adgn.llm.mcp.types import ServerSlot, ServerSlotSpec

# Shared MCP naming helpers/constants
MCP_NAMESPACE_PREFIX = "mcp__"


def build_mcp_function(server: str, tool: str) -> str:
    """Compose the canonical namespaced MCP tool name.

    Single source of truth for composing names like "mcp__{server}__{tool}".
    Do not hand-roll f-strings elsewhere; always use this helper.
    Mostly an implementation detail of McpManager; occasionally useful in tests
    or when composing prompts for LLMs.
    """
    return f"{MCP_NAMESPACE_PREFIX}{server}__{tool}"


def parse_mcp_function(namespaced: str) -> tuple[str, str]:
    """Parse a canonical namespaced MCP tool name into (server, tool).

    Single source of truth for parsing names like "mcp__{server}__{tool}".
    Never parse with ad-hoc string ops elsewhere; always call this helper.
    Mostly an implementation detail of McpManager; occasionally useful in tests
    or when composing prompts for LLMs.
    """
    # Accept both prefixed (mcp__server__tool) and bare (server__tool) forms
    if namespaced.startswith(MCP_NAMESPACE_PREFIX):
        remainder = namespaced[len(MCP_NAMESPACE_PREFIX) :]
    else:
        remainder = namespaced
    if "__" not in remainder:
        raise ValueError(f"Invalid MCP tool name: {namespaced}")
    server, tool = remainder.split("__", 1)
    return server, tool


# ---- Legacy in-proc adapter removed (use FastMCP in-proc memory transport) ----


# ---- Notification models (module-level) ----
class ResourceUpdateEvent(BaseModel):
    server: str
    uri: str
    version: int  # monotonically increasing counter per (server, uri)


class NotificationsBatch(BaseModel):
    resources_updated: list[ResourceUpdateEvent] = Field(default_factory=list)
    tools_invalidated: list[str] = Field(default_factory=list)


class McpManager:
    """Per-agent bag of MCP sessions; lazy-open; one lifetime (AsyncExitStack)."""

    def __init__(self, specs: dict[str, ServerSlotSpec]):
        # Always include the resources shim server; reserve the name 'resources'
        self._specs = dict(specs)
        assert "resources" not in self._specs, (
            "'resources' server name is reserved; McpManager injects it automatically"
        )
        resources_server = make_resources_server(self, "resources")
        self._specs["resources"] = make_inproc_slot_spec(resources_server)

        self._realized: dict[str, ServerSlot] = {}
        self._stack = AsyncExitStack()
        self._entered = False
        self._lock: asyncio.Lock | None = (
            None  # bound in __aenter__ to the running loop
        )
        # Track servers that failed to open during eager initialization
        self._open_errors: dict[str, str] = {}
        # Tools cache (namespaced tool defs)
        self._tools_cache_by_server: dict[str, list[dict[str, Any]]] = {}
        # Notification buffers and version counters
        self._notif_tools_invalidated: set[str] = set()
        self._notif_resource_updates: list[dict[str, Any]] = []
        self._resource_version: dict[
            tuple[str, str], int
        ] = {}  # (server, uri) -> version counter

    async def _ensure_stack_entered(self) -> None:
        if not self._entered:
            await self._stack.__aenter__()
            self._entered = True

    async def ensure_open(self, name: str) -> ServerSlot:
        if not self._entered or self._lock is None:
            raise RuntimeError(
                "McpManager must be entered (await __aenter__) before ensure_open"
            )
        async with self._lock:
            await self._ensure_stack_entered()
            # If this server previously failed to open, surface the error immediately
            if name in self._open_errors:
                raise RuntimeError(
                    f"Server '{name}' failed to open: {self._open_errors[name]}"
                )
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
        if not self._entered:
            await self._stack.__aenter__()
            self._entered = True
            # Create a lock bound to this running event loop; all ops must occur under this loop
            self._lock = asyncio.Lock()
            # Eagerly open all specs in the owner task; record failures immediately
            for name, spec in self._specs.items():
                try:
                    if name not in self._realized:
                        self._realized[name] = await spec.open(self._stack)
                except Exception as e:
                    # Record error; subsequent ensure_open/get_server_initialize will surface it
                    self._open_errors[name] = str(e)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # Delegate shutdown entirely to the AsyncExitStack to ensure all contexts
        # (server task group, client session) are exited in the same task/cancel scope
        # they were entered in. Avoid pre-shutdown; let context managers unwind.
        if self._entered:
            await self._stack.__aexit__(exc_type, exc, tb)
            self._entered = False
        self._realized.clear()

    async def get_session(self, name: str) -> ClientSession:
        return (await self.ensure_open(name)).session

    def invalidate_tools_cache_for(self, *servers: str) -> None:
        """Invalidate cached tool definitions for specific servers (varargs)."""
        for s in servers:
            self._tools_cache_by_server.pop(s, None)

    async def list_tools(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        targets = only or list(self._specs.keys())
        for name in targets:
            cached = self._tools_cache_by_server.get(name)
            if cached is None:
                sess = await self.get_session(name)
                res = await sess.list_tools()
                cached = [
                    {
                        "type": "function",
                        "name": build_mcp_function(name, t.name),
                        "description": t.description or "",
                        "parameters": t.inputSchema,
                    }
                    for t in (res.tools or [])
                ]
                self._tools_cache_by_server[name] = cached
            out.extend(cached)
        return out

    async def list_resources(
        self,
        only: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return a fresh view of resources across servers.

        Each item: {server, uri, name?, description?, mime?, annotations?}
        """
        items: list[dict[str, Any]] = []
        for server_name in only or list(self._specs.keys()):
            # Skip the synthetic 'resources' server to avoid self-recursion
            if server_name == "resources":
                continue

            # Check server capabilities from initialize; skip if resources unsupported
            init = await self.get_server_initialize(server_name)
            if not self._supports_resources_from_init(init):
                continue

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
                    },
                )
        return items

    async def read_resource(self, server: str, uri: str) -> Any:
        """Thin wrapper around ClientSession.read_resource(uri)."""
        sess = await self.get_session(server)
        # ClientSession.read_resource expects AnyUrl; inputs come as strings
        return await sess.read_resource(cast(AnyUrl, uri))

    @staticmethod
    def parse_args_json(args_json: str | None) -> dict[str, Any]:
        """Parse tool arguments from JSON string to dict.

        Raises ValueError on invalid JSON or non-object payload.
        """
        if not args_json:
            return {}
        try:
            obj = json.loads(args_json)
        except Exception as e:
            raise ValueError("invalid tool arguments JSON") from e
        if not isinstance(obj, dict):
            raise ValueError("tool arguments JSON must be an object")
        return obj

    async def call_tool(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any] | str | None,
    ) -> Any:
        """Call a named tool on a named server.

        Accepts either a dict (already parsed) or a raw JSON string; strings are parsed here.
        """
        sess = await self.get_session(server)
        if isinstance(arguments, dict):
            args_dict = arguments
        else:
            try:
                args_dict = self.parse_args_json(arguments)
            except ValueError as e:
                # Report as a failed tool call (structured error) instead of silently swallowing
                return mcp_types.CallToolResult(
                    content=[],
                    isError=True,
                    structuredContent={"ok": False, "error": str(e)},
                )
        return await sess.call_tool(name=name, arguments=args_dict)

    async def call_tool_typed(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any] | str | None,
        result_model: type,
    ) -> Any:
        """Call a tool and validate the structured 'result' payload into result_model.

        Contract: the server MUST return a structured payload under structuredContent['result'] (a native JSON tree).
        This method enforces that invariant and uses pydantic.TypeAdapter to validate/parse into the provided
        Pydantic model or typing annotation (Annotated/Union). If the invariant is broken, raise ValueError.
        """
        res = await self.call_tool(server, name, arguments)
        structured = getattr(res, "structuredContent", None)
        if not isinstance(structured, dict) or "result" not in structured:
            raise ValueError(
                f"Tool {server}/{name} did not return a structured 'result' payload",
            )
        payload = structured["result"]
        return TypeAdapter(result_model).validate_python(payload)

    async def call_tool_namespaced(
        self,
        namespaced: str,
        arguments: dict[str, Any] | str | None,
    ) -> Any:
        """Call a tool specified by namespaced form 'mcp__{server}__{tool}'."""
        server, tool = parse_mcp_function(namespaced)
        return await self.call_tool(server, tool, arguments)

    async def get_server_initialize(self, server: str) -> InitializeResult:
        """Return the InitializeResult for a server from the cached slot after opening."""
        slot = await self.ensure_open(server)
        return slot.init_result

    # ---- Notifications: buffer and API ----

    def notify_tools_list_changed(self, server: str) -> None:
        """Record a tools list change and invalidate that server's cache."""
        self._notif_tools_invalidated.add(server)
        self.invalidate_tools_cache_for(server)

    def notify_resource_updated(self, server: str, uri: str) -> None:
        """Record a resource update and bump its per-(server, uri) version."""
        key = (server, uri)
        self._resource_version[key] = self._resource_version.get(key, 0) + 1
        self._notif_resource_updates.append(
            {"server": server, "uri": uri, "version": self._resource_version[key]}
        )

    def poll_notifications(self) -> NotificationsBatch:
        """Return and clear buffered notifications (for agent injection as transcript FYIs)."""
        batch = NotificationsBatch(
            resources_updated=[
                ResourceUpdateEvent(**e) for e in self._notif_resource_updates
            ],
            tools_invalidated=sorted(self._notif_tools_invalidated),
        )
        self._notif_resource_updates.clear()
        self._notif_tools_invalidated.clear()
        return batch

    # ---- Capability helpers ----
    @staticmethod
    def _supports_resources_from_init(init: InitializeResult) -> bool:
        """Return True if initialize.capabilities.resources is truthy.

        Prefer attribute-style capabilities; support dict-capabilities explicitly.
        """
        caps = init.capabilities
        if isinstance(caps, dict):
            return bool(caps.get("resources"))
        return bool(caps.resources)

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
        resources: list[McpManager.ResourceItem]

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
        window: McpManager.Window
        parts: list[McpManager.ResourcePart]
        total_parts: int

    # ---- Resource helpers (typed) ----
    async def resources_list(
        self,
        req: McpManager.ResourcesListRequest,
    ) -> McpManager.ResourcesListResponse:
        items_raw = await self.list_resources(only=[req.server] if req.server else None)
        if req.uri_prefix:
            items_raw = [
                it
                for it in items_raw
                if isinstance(it.get("uri"), str)
                and it["uri"].startswith(req.uri_prefix)
            ]
        items = [self.ResourceItem(**it) for it in items_raw]
        return self.ResourcesListResponse(resources=items)

    async def resources_read(
        self,
        req: McpManager.ResourcesReadRequest,
    ) -> McpManager.ResourcesReadResponse:
        res = await self.read_resource(req.server, req.uri)
        contents = getattr(res, "contents", None) or []

        # typed window build
        class _Part(Protocol):
            mimeType: str | None  # noqa: N815
            text: str | None
            data: str | None

        parts_out: list[McpManager.ResourcePart] = []
        contents = res.contents or []
        for part in self._iter_window_parts(contents, req.start_offset, req.max_bytes):
            if part["kind"] == "text":
                parts_out.append(
                    self.ResourcePartText(
                        mime=part["mime"],
                        text=part["text"],
                        total_bytes=part["total_bytes"],
                        bytes_returned=part["bytes_returned"],
                    ),
                )
            else:
                parts_out.append(
                    self.ResourcePartBase64(
                        mime=part["mime"],
                        base64=part["base64"],
                        total_bytes=part["total_bytes"],
                        bytes_returned=part["bytes_returned"],
                    ),
                )
        return self.ResourcesReadResponse(
            window=self.Window(start_offset=req.start_offset, max_bytes=req.max_bytes),
            parts=parts_out,
            total_parts=len(contents),
        )

    async def resources_list_json(
        self,
        server_filter: str | None,
        uri_prefix: str | None,
    ) -> str:
        resp = await self.resources_list(
            self.ResourcesListRequest(server=server_filter, uri_prefix=uri_prefix),
        )
        return json.dumps(resp.model_dump(exclude_none=True), ensure_ascii=False)

    @staticmethod
    def _iter_window_parts(
        contents: list[Any],
        start_offset: int,
        max_bytes: int | None,
    ):
        class _Part(Protocol):
            mimeType: str | None  # noqa: N815
            text: str | None
            data: str | None

        remaining: int | None = max_bytes if isinstance(max_bytes, int) else None
        cursor = 0
        for any_p in contents or []:
            p = cast(_Part, any_p)
            if isinstance(p.text, str):
                raw = p.text.encode("utf-8")
                total_len = len(raw)
                if remaining is None or remaining > 0:
                    start_in_part = max(0, start_offset - cursor)
                    take_cap = remaining if isinstance(remaining, int) else total_len
                    take = max(0, min(take_cap, total_len - start_in_part))
                    if take > 0:
                        chunk = raw[start_in_part : start_in_part + take]
                        yield {
                            "kind": "text",
                            "mime": p.mimeType,
                            "text": chunk.decode("utf-8", errors="replace"),
                            "total_bytes": total_len,
                            "bytes_returned": take,
                        }
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
                        yield {
                            "kind": "base64",
                            "mime": p.mimeType,
                            "base64": base[start_in_part : start_in_part + take],
                            "total_bytes": total_len,
                            "bytes_returned": take,
                        }
                        if remaining is not None:
                            remaining -= take
            cursor += (
                len(p.text.encode("utf-8"))
                if isinstance(p.text, str)
                else len(p.data or "")
            )
            if remaining is not None and remaining <= 0:
                break

    @staticmethod
    def _build_resource_window(
        contents: list[Any],
        start_offset: int,
        max_bytes: int | None,
    ) -> dict[str, Any]:
        parts_out: list[dict[str, Any]] = []
        for part in McpManager._iter_window_parts(contents, start_offset, max_bytes):
            parts_out.append(
                {
                    k: v
                    for k, v in part.items()
                    if k
                    in {
                        "kind",
                        "mime",
                        "text",
                        "base64",
                        "total_bytes",
                        "bytes_returned",
                    }
                },
            )
        return {
            "window": {"start_offset": start_offset, "max_bytes": max_bytes},
            "parts": parts_out,
            "total_parts": len(contents or []),
        }

    async def resources_read_json(
        self,
        server: str,
        uri: str,
        start_offset: int,
        max_bytes: int | None,
    ) -> str:
        """Return JSON string for a resource read window payload (server, uri)."""
        res = await self.read_resource(server, uri)
        contents = res.contents or []
        payload = self._build_resource_window(contents, start_offset, max_bytes)
        return json.dumps(payload, ensure_ascii=False)

    @property
    def server_names(self) -> list[str]:
        """Configured server names (public API)."""
        return list(self._specs.keys())

    # ---- Structured sampling snapshot (no prompt rendering) ----
    class InitializeView(BaseModel):
        instructions: str | None = None
        server_info: Any | None = None

    class ServerEntry(BaseModel):
        name: str
        state: Literal["running", "failed"]
        initialize: McpManager.InitializeView | None = None
        error: str | None = None

    class ToolDef(BaseModel):
        type: Literal["function"] = "function"
        name: str
        description: str = ""
        parameters: dict[str, Any] = Field(default_factory=dict)

    class SamplingSnapshot(BaseModel):
        servers: list[McpManager.ServerEntry]
        tools: list[McpManager.ToolDef]

    async def sampling_snapshot(self) -> McpManager.SamplingSnapshot:
        servers: list[McpManager.ServerEntry] = []
        running: list[str] = []
        for name in self.server_names:
            try:
                init_res = await self.get_server_initialize(name)
                servers.append(
                    self.ServerEntry(
                        name=name,
                        state="running",
                        initialize=self.InitializeView(
                            instructions=init_res.instructions,
                            server_info=init_res.serverInfo,
                        ),
                    )
                )
                running.append(name)
            except Exception as e:
                servers.append(
                    self.ServerEntry(name=name, state="failed", error=str(e))
                )
        tools_raw = await self.list_tools(only=running)
        tools = [self.ToolDef(**t) for t in tools_raw]
        return self.SamplingSnapshot(servers=servers, tools=tools)

    @staticmethod
    def slot_from_spec(name: str, spec: Any) -> ServerSlotSpec:
        """Create a ServerSlotSpec from a transport spec.

        Accepted shapes:
        - Dict with explicit "transport": "stdio" | "sse" | "http" parsed via the corresponding Pydantic params

        IMPORTANT: This function implements the ONE supported OpenFn API: each
        returned open_uninitialized must accept an AsyncExitStack and register all
        subordinate contexts (streams, task-groups, ClientSession) on that stack by
        calling stack.enter_async_context(...).

        Why: transports and sessions create internal anyio task-groups during
        __aenter__ which must be *entered* and *exited* in the same task/cancel
        scope. By centralizing entry/exit on the manager's AsyncExitStack we avoid
        cross-task cancel-scope mismatches and ensure deterministic teardown.
        """
        if not isinstance(spec, dict):
            raise TypeError(
                f"Unsupported MCP server spec type for {name!r}: {type(spec)!r}",
            )

        transport = spec.get("transport")
        if transport is None and any(k in spec for k in ("command", "args", "env")):
            transport = "stdio"

        if transport == "stdio":
            params = StdioServerParameters.model_validate(spec)

            def open_uninitialized(
                stack: AsyncExitStack,
            ) -> AbstractAsyncContextManager[ClientSession]:
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
                        pass

                return _ctx()

            return ServerSlotSpec(open_uninitialized=open_uninitialized)

        if transport == "inproc":
            # Expect a FastMCP server object under key 'server'
            server_obj = spec.get("server")
            if server_obj is None:
                raise ValueError(
                    "inproc transport requires a 'server' FastMCP instance in spec",
                )
            return make_inproc_slot_spec(server_obj)

        if transport == "sse":
            url_val = spec.get("url")
            if not isinstance(url_val, str) or not url_val:
                raise ValueError(
                    "SSE transport requires a non-empty 'url' string in spec",
                )
            headers = spec.get("headers")
            timeout = spec.get("timeout", 5)
            sse_read_timeout = spec.get("sse_read_timeout", 60 * 5)

            def open_uninitialized(
                stack: AsyncExitStack,
            ) -> AbstractAsyncContextManager[ClientSession]:
                """Return an async context manager that yields an UNINITIALIZED ClientSession for SSE transport."""

                @asynccontextmanager
                async def _ctx():
                    read, write = await stack.enter_async_context(
                        sse_client(
                            url=url_val,
                            headers=headers,
                            timeout=timeout,
                            sse_read_timeout=sse_read_timeout,
                        ),
                    )
                    sess = ClientSession(read_stream=read, write_stream=write)
                    await stack.enter_async_context(sess)
                    try:
                        yield sess
                    finally:
                        pass

                return _ctx()

            return ServerSlotSpec(open_uninitialized=open_uninitialized)

        # HTTP transport not supported in this environment version; add when needed.
        raise ValueError(
            f"Unsupported or missing transport in spec for {name!r} (keys={list(spec.keys())!r})",
        )

    @staticmethod
    # TODO(mpokorny): If needed later, add an 'inproc' transport that loads a dotted factory path
    # to create a FastMCP server in-proc from JSON config. For now, prefer explicit wiring in code.
    def slots_from_specs(specs: dict[str, Any]) -> dict[str, ServerSlotSpec]:
        """Parse a mapping of name→transport spec into ServerSlotSpec entries.

        Each entry yields an UNINITIALIZED ClientSession when opened; initialization
        is performed exactly once in ServerSlotSpec.open().
        """
        return {
            name: McpManager.slot_from_spec(name, spec) for name, spec in specs.items()
        }

    # NOTE: parse_mcp_function is provided as a top-level helper for parsing namespaced
    # MCP tool identifiers (mcp__{server}__{tool}). The instance-level resolve_function
    # method was removed: call_tool() now accepts the single namespaced identifier and
    # parses it internally. Keep parse_mcp_function exported for callers that need to
    # parse names directly (tests and event renderers).


# NotificationsBatch and ResourceUpdateEvent are defined at module level (above)
