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
        # Do not eagerly open specs; let ensure_open() realize them in this loop
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # Gracefully shut down realized slots (servers/sessions) first so any
        # background tasks they spawned are awaited/cancelled under this
        # coroutine's cancel scope. This avoids the anyio "exit cancel scope in a
        # different task" error caused when tasks are created in a different
        # cancel scope than the one performing shutdown.
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
        if self._entered:
            await self._stack.__aexit__(exc_type, exc, tb)
            self._entered = False

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
                        "name": build_mcp_function(name, t.name),
                        "description": t.description or "",
                        "parameters": t.inputSchema,
                    },
                )
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
