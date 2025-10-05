"""MCP session manager — per-agent, FastMCP-first, DRY wiring.

- Per-agent isolation: each agent builds its own McpManager (its own sessions)
- One lifetime boundary: AsyncExitStack on the manager
- Transport-invariant wiring: ServerSlotSpec.open performs initialize exactly once; open_uninitialized returns an uninitialized ClientSession
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
import importlib
import json
import logging
from typing import Annotated, Any, Literal, Mapping, Optional

import anyio
from mcp import types as mcp_types
from mcp.client.session import ClientSession, MessageHandlerFnT
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import InitializeResult
from pydantic import AnyUrl, BaseModel, Field, TypeAdapter

from adgn.agent.runtime.specs import McpServerSpec
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.mcp.resources.server import ResourceEntry, make_resources_server
from adgn.mcp.types import ServerSlot, ServerSlotSpec

logger = logging.getLogger(__name__)

# Shared MCP naming helpers/constants
MCP_NAMESPACE_PREFIX = "mcp__"
_ANY_URL: TypeAdapter[AnyUrl] = TypeAdapter(AnyUrl)


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

    def __init__(self, specs: dict[str, McpServerSpec], *, eager_open: bool = True):
        # Convert incoming typed transport specs to runtime slots
        self._specs: dict[str, ServerSlotSpec] = self.slots_from_specs(specs)
        assert "resources" not in self._specs, (
            "'resources' server name is reserved; McpManager injects it automatically"
        )
        resources_server = make_resources_server(self, "resources")
        self._specs["resources"] = make_inproc_slot_spec(
            resources_server,
            message_handler=self._make_message_handler("resources"),
        )
        # Per-server state bundle (worker + realized slot)
        self._servers: dict[str, "_ServerState"] = {}
        # Seed per-server state with specs
        for name, slot_spec in self._specs.items():
            st = self._state(name)
            st.spec = slot_spec

        # Deprecated: manager-level stack (left for backward compatibility; no longer used for session entry)
        self._stack = AsyncExitStack()
        self._entered = False
        self._lock: asyncio.Lock | None = None  # bound in __aenter__ to the running loop
        self._eager_open = eager_open
        # Notification buffers and version counters
        self._notif_tools_invalidated: set[str] = set()
        self._notif_resource_updates: list[ResourceUpdateEvent] = []
        # Idle-drain accounting for client-initiated RPCs
        self._inflight: int = 0
        self._idle_event: asyncio.Event | None = None  # bound in __aenter__
        # Closing latch to signal client teardown in progress
        self._closing: bool = False
        # Track in-flight client requests per server for protocol-level cancellation
        self._inflight_lock = asyncio.Lock()

    def _state(self, name: str) -> "_ServerState":
        """Get or create the per-server state bundle."""
        # Be robust if _servers hasn't been initialized yet (e.g., subclassing or
        # early calls during __init__ failures). Initialize on first access.
        if not hasattr(self, "_servers") or self._servers is None:  # type: ignore[has-type]
            self._servers = {}
        st = self._servers.get(name)
        if st is None:
            st = _ServerState()
            self._servers[name] = st
        return st

    async def _ensure_stack_entered(self) -> None:
        # No-op for worker-based lifecycle; retain for compatibility
        if not self._entered:
            await self._stack.__aenter__()
            self._entered = True

    async def ensure_open(self, name: str) -> ServerSlot:
        if not self._entered or self._lock is None:
            raise RuntimeError("McpManager must be entered (await __aenter__) before ensure_open")
        async with self._lock:
            # If known failed, surface early (callers may retry after reattach)
            st0 = self._servers.get(name)
            try:
                print(
                    f"[McpManager.ensure_open] after get(name) st0={'set' if st0 else 'none'} for {name}"
                )
            except Exception:
                pass
            if st0 and st0.error:
                raise RuntimeError(f"Server '{name}' failed to open: {st0.error}")
            # Fast path from per-server state
            st_cur = self._servers.get(name)
            st_slot = st_cur.slot if st_cur is not None else None
            try:
                print(
                    f"[McpManager.ensure_open] fast-path slot={'yes' if st_slot else 'no'} for {name}"
                )
            except Exception:
                pass
            if st_slot is not None:
                return st_slot
            # Ensure worker exists
            st = self._state(name)
            try:
                print(f"[McpManager.ensure_open] got state for {name}")
            except Exception:
                pass
            w = st.worker
            try:
                print(f"[McpManager.ensure_open] worker is {'present' if w else 'none'} for {name}")
            except Exception:
                pass
            if w is None:
                spec = self._specs.get(name)
                try:
                    print(
                        f"[McpManager.ensure_open] spec is {'present' if spec else 'none'} for {name}"
                    )
                except Exception:
                    pass
                if spec is None:
                    raise KeyError(f"Unknown MCP server slot: {name}")
                w = _ServerWorker(self, name, spec)
                st.worker = w
                w.start()
        # Await readiness outside the manager lock to avoid blocking others
        st_wait = self._servers.get(name)
        if st_wait is None or st_wait.worker is None:
            raise RuntimeError(f"Server '{name}' worker missing before wait_ready")
        await st_wait.worker.wait_ready()
        w2 = st_wait.worker
        if w2 is None:
            raise RuntimeError(f"Server '{name}' worker missing after start")
        if w2.error is not None:
            # Cache error and raise
            async with self._lock:
                self._state(name).error = w2.error
            raise RuntimeError(f"Server '{name}' failed to open: {w2.error}")
        if w2.slot is None:
            raise RuntimeError(f"Server '{name}' slot not available after open")
        # Cache realized slot for quick path
        async with self._lock:
            self._state(name).slot = w2.slot
        return w2.slot

    async def __aenter__(self) -> "McpManager":
        if not self._entered:
            await self._stack.__aenter__()
            self._entered = True
            # Create a lock bound to this running event loop; all ops must occur under this loop
            self._lock = asyncio.Lock()
            self._idle_event = asyncio.Event()
            self._idle_event.set()
            # Eagerly open all configured servers in parallel if requested
            if self._eager_open:
                # Spawn workers (skip reserved 'resources')
                for name, spec in self._specs.items():
                    if name == "resources":
                        continue
                    st = self._state(name)
                    if st.worker is None:
                        st.worker = _ServerWorker(self, name, spec)
                        st.worker.start()
                # Await readiness for all spawned workers
                await asyncio.gather(
                    *[
                        st.worker.wait_ready()
                        for st in self._servers.values()
                        if st.worker is not None
                    ],
                    return_exceptions=True,
                )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # Mark closing and wait until no client-initiated RPCs remain before teardown
        self._closing = True
        await self.wait_idle(timeout=None)
        # Stop all workers and await exit
        workers = [st.worker for st in self._servers.values() if st.worker is not None]
        for w in workers:
            w.stop()
        await asyncio.gather(
            *(w.task for w in workers if w.task is not None), return_exceptions=True
        )
        self._servers.clear()
        if self._entered:
            await self._stack.__aexit__(exc_type, exc, tb)
            self._entered = False

    def is_closing(self) -> bool:
        """Return True if manager shutdown is in progress."""
        return self._closing

    def is_entered(self) -> bool:
        """Return True if the manager has been entered via __aenter__()."""
        return bool(self._entered)

    async def detach_server(self, name: str) -> None:
        """Close and remove a realized server slot and drop its spec."""
        if name == "resources":
            raise ValueError("'resources' server cannot be detached")
        # Stop and remove worker
        st = self._servers.pop(name, None)
        w = st.worker if st else None
        self._specs.pop(name, None)
        if w is not None:
            w.stop()
            if w.task is not None:
                await asyncio.gather(w.task, return_exceptions=True)
        # Clear cached state for detached server
        if st:
            st.tools_cache = None
            st.error = None
            st.init = None
            st.supports_resources = None

    # Removed: previous wrapper installed a private `_message_handler` on sessions.
    # All transports now pass `message_handler` during ClientSession construction,
    # including in-proc (see make_inproc_slot_spec(...)). No private attributes used.

    async def attach_server(self, name: str, spec: ServerSlotSpec | McpServerSpec) -> None:
        """Attach or replace a server spec and ensure it is open.

        Public API for live reconfiguration; avoids external mutation of private fields.
        """
        if name == "resources":
            # Reserved and injected automatically
            return
        # Accept either a ready-to-open ServerSlotSpec or a typed transport spec; coerce if needed.
        slot_spec: ServerSlotSpec
        if isinstance(spec, ServerSlotSpec):
            # Wrap the provided spec to ensure our message handler is installed on the session
            original = spec

            def open_uninitialized(stack: AsyncExitStack):
                @asynccontextmanager
                async def _cm():
                    async with original.open_uninitialized(stack) as sess:
                        # Inject our message handler so server-side notifications are captured.
                        # This relies on ClientSession supporting a private '_message_handler' field. If this fails,
                        # the error should surface so the caller can attach via typed specs that install handlers.
                        handler = self._make_message_handler(name)
                        setattr(sess, "_message_handler", handler)
                        yield sess

                return _cm()

            slot_spec = ServerSlotSpec(
                open_uninitialized=open_uninitialized,
                init_timeout_secs=getattr(spec, "init_timeout_secs", None),
            )
        else:
            slot_spec = self.slot_from_spec(name, spec)
        self._specs[name] = slot_spec
        self._state(name).spec = slot_spec
        # Clear any prior open failure state to allow retry on fresh attach
        self._state(name).error = None
        # Ensure open so we can install a message handler fallback for externally built slots
        slot = await self.ensure_open(name)
        try:
            if getattr(slot.session, "_message_handler", None) is None:
                setattr(slot.session, "_message_handler", self._make_message_handler(name))
        except Exception as e:
            logger.debug("failed to set _message_handler on session: %s", e)

    async def reconfigure(self, desired: dict[str, ServerSlotSpec]) -> None:
        """Converge to the desired set of server specs (full replacement).

        Detaches any servers not present in desired (except 'resources'), and attaches
        or updates those present in desired. Attachment opens connections eagerly.
        """
        current = set(self._specs.keys())
        wanted = set(desired.keys())
        for name in current - wanted:
            if name == "resources":
                continue
            await self.detach_server(name)
        for name, spec in desired.items():
            old = self._specs.get(name)
            if old != spec:
                await self.attach_server(name, spec)

    async def wait_idle(self, timeout: float | None = 1.0) -> None:
        """Wait until there are no client-initiated RPCs in flight.

        This guards against tearing down in-proc transports while background
        request responders are unwinding their cancel scopes.
        """
        ev = self._idle_event
        if ev is None:
            return
        if self._inflight == 0 and ev.is_set():
            return
        if timeout is None:
            await ev.wait()
            return
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    def _inflight_begin(self) -> None:
        ev = self._idle_event
        self._inflight += 1
        if ev is not None:
            ev.clear()

    def _inflight_end(self) -> None:
        ev = self._idle_event
        if self._inflight > 0:
            self._inflight -= 1
        if self._inflight == 0 and ev is not None:
            ev.set()

    async def get_session(self, name: str) -> ClientSession:
        return (await self.ensure_open(name)).session

    async def get_server_initialize(self, server: str) -> InitializeResult:
        """Return the InitializeResult for a server, using cached state when available."""
        # Fast path from cache
        st = self._servers.get(server)
        if st and st.init is not None:
            return st.init
        # Ensure open, then read from slot and update cache
        slot = await self.ensure_open(server)
        init = slot.init_result
        st2 = self._state(server)
        st2.init = init
        # Also cache supports_resources for convenience
        st2.supports_resources = self._supports_resources_from_init(init)
        return init

    def invalidate_tools_cache_for(self, *servers: str) -> None:
        """Invalidate cached tool definitions for specific servers (varargs)."""
        for s in servers:
            st = self._servers.get(s)
            if st is not None:
                st.tools_cache = None

    async def list_tools(self, only: list[str] | None = None) -> list[ToolEntry]:
        out: list[ToolEntry] = []
        targets = only or list(self._specs.keys())
        self._inflight_begin()
        try:
            for name in targets:
                # Skip known-failed servers
                st = self._servers.get(name)
                if st and st.error:
                    continue
                cached = st.tools_cache if st else None
                if cached is None:
                    try:
                        sess = await self.get_session(name)
                        res = await sess.list_tools()
                        cached = list(res.tools or [])
                        # Cache tools and clear any prior error
                        st2 = self._state(name)
                        st2.tools_cache = cached
                        st2.error = None
                    except Exception as e:
                        # Mark as failed and continue with other servers
                        msg = f"{type(e).__name__}: {e}"
                        logger.warning(
                            "list_tools failed; server marked as failed",
                            extra={"server": name, "error": msg},
                        )
                        self._state(name).error = msg
                        continue
                # Emit tool entries for this server
                out.extend(ToolEntry(server=name, tool=t) for t in (cached or []))
            return out
        finally:
            self._inflight_end()

    def _wrap_session(self, session: ClientSession, server_name: str) -> None:
        """Monkey-patch send_request to record outgoing request IDs for cancellation.

        Safe to call multiple times per session; wrapping occurs only once.
        """
        if getattr(session, "_adgn_wrapped_send_request", False):
            return
        orig_send_request = session.send_request

        manager = self

        async def send_request_wrapped(request, result_type, *args, **kwargs):  # type: ignore[no-untyped-def]
            # Capture the request id that will be used by BaseSession.send_request
            req_id = None
            try:
                req_id = getattr(session, "_request_id", None)
                if not isinstance(req_id, int):
                    req_id = None
            except Exception:
                req_id = None
            if req_id is not None:
                async with manager._inflight_lock:
                    st = manager._state(server_name)
                    st.inflight_ids.add(req_id)
            try:
                return await orig_send_request(request, result_type, *args, **kwargs)
            finally:
                if req_id is not None:
                    async with manager._inflight_lock:
                        st2 = manager._servers.get(server_name)
                        if st2 is not None:
                            st2.inflight_ids.discard(req_id)

        session.send_request = send_request_wrapped  # type: ignore[attr-defined]
        setattr(session, "_adgn_wrapped_send_request", True)

    async def cancel_all_outgoing(self, reason: str | None = None) -> int:
        """Send MCP protocol cancellations for all in-flight requests across sessions.

        Returns the number of cancellation notifications sent.
        """
        total = 0
        async with self._inflight_lock:
            for name, st in list(self._servers.items()):
                if not st.inflight_ids:
                    continue
                if st.slot is None:
                    continue
                session = st.slot.session
                for req_id in list(st.inflight_ids):
                    note = mcp_types.ClientNotification(
                        mcp_types.CancelledNotification(
                            params=mcp_types.CancelledNotificationParams(
                                requestId=req_id, reason=reason
                            )
                        )
                    )
                    await session.send_notification(note)
                    total += 1
        return total

    async def list_resources(
        self,
        only: list[str] | None = None,
    ) -> list[ResourceEntry]:
        """Return a fresh view of resources across servers.

        Each item: {server, uri, name?, description?, mime?, annotations?}
        """
        items: list[ResourceEntry] = []
        self._inflight_begin()
        try:
            for server_name in only or list(self._specs.keys()):
                # Skip the synthetic 'resources' server to avoid self-recursion
                if server_name == "resources":
                    continue
                # Skip known-failed servers
                stA = self._servers.get(server_name)
                if stA and stA.error:
                    continue
                # Check cached capability; if unknown, fetch and cache it
                st_cap = self._servers.get(server_name)
                if st_cap is None or st_cap.supports_resources is None:
                    try:
                        await self.get_server_initialize(server_name)
                    except Exception as e:
                        # Mark as failed and continue
                        msg = f"{type(e).__name__}: {e}"
                        logger.warning(
                            "get_server_initialize failed; server marked as failed",
                            extra={"server": server_name, "error": msg},
                        )
                        self._state(server_name).error = msg
                        continue
                # Re-read after potential update
                st_cap = self._servers.get(server_name)
                if st_cap and st_cap.supports_resources is False:
                    continue
                try:
                    sess = await self.get_session(server_name)
                    res = await sess.list_resources()
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    logger.warning(
                        "list_resources failed; server marked as failed",
                        extra={"server": server_name, "error": msg},
                    )
                    self._state(server_name).error = msg
                    continue
                for r in res.resources or []:
                    items.append(ResourceEntry(server=server_name, resource=r))
            return items
        finally:
            self._inflight_end()

    async def read_resource(self, server: str, uri: str) -> mcp_types.ReadResourceResult:
        """Thin wrapper around ClientSession.read_resource(uri)."""
        self._inflight_begin()
        try:
            sess = await self.get_session(server)
            # ClientSession.read_resource expects AnyUrl; inputs come as strings
            uri_value = _ANY_URL.validate_python(uri)
            return await sess.read_resource(uri_value)
        finally:
            self._inflight_end()

    @staticmethod
    def parse_args_json(args_json: str | None) -> dict[str, Any]:
        """Parse tool arguments from JSON string to dict.

        Raises ValueError on invalid JSON or non-object payload.
        """
        if not args_json:
            return {}
        try:
            obj = json.loads(args_json)
        except json.JSONDecodeError as e:
            raise ValueError("invalid tool arguments JSON") from e
        if not isinstance(obj, dict):
            raise ValueError("tool arguments JSON must be an object")
        return obj

    async def call_tool(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any] | str | None,
    ) -> mcp_types.CallToolResult:
        """Call a named tool on a named server.

        Accepts either a dict (already parsed) or a raw JSON string; strings are parsed here.
        """
        self._inflight_begin()
        try:
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
        finally:
            self._inflight_end()

    async def call_tool_typed(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any] | str | None,
        result_model: type,
    ) -> Any:
        """Call a tool and validate the structured 'result' payload into result_model.

        Structured payload is taken from CallToolResult.structuredContent. The content may be a dict/list/scalar
        per tool definition; no additional wrapping is assumed.
        """
        res = await self.call_tool(server, name, arguments)
        payload = res.structuredContent
        # Unwrap common {'result': ...} shape if present
        if isinstance(payload, dict) and "result" in payload and len(payload) == 1:
            payload = payload["result"]
        return TypeAdapter(result_model).validate_python(payload)

    async def call_tool_namespaced(
        self,
        namespaced: str,
        arguments: dict[str, Any] | str | None,
    ) -> mcp_types.CallToolResult:
        """Call a tool specified by namespaced form 'mcp__{server}__{tool}'."""
        server, tool = parse_mcp_function(namespaced)
        return await self.call_tool(server, tool, arguments)

    # ---- Notifications: buffer and API ----

    def notify_tools_list_changed(self, server: str) -> None:
        """Record a tools list change and invalidate that server's cache."""
        self._notif_tools_invalidated.add(server)
        self.invalidate_tools_cache_for(server)

    def notify_resource_updated(self, server: str, uri: str) -> None:
        """Record a resource update and bump its per-(server, uri) version."""
        # TODO(mpokorny): Client-side subscription filtering is not implemented.
        # We forward subscribe/unsubscribe to servers, but we still buffer
        # all ResourceUpdated notifications received from sessions.
        st = self._state(server)
        st.resource_versions[uri] = st.resource_versions.get(uri, 0) + 1
        self._notif_resource_updates.append(
            ResourceUpdateEvent(server=server, uri=uri, version=st.resource_versions[uri])
        )

    def poll_notifications(self) -> NotificationsBatch:
        """Return and clear buffered notifications (for agent injection as transcript FYIs)."""
        batch = NotificationsBatch(
            resources_updated=list(self._notif_resource_updates),
            tools_invalidated=sorted(self._notif_tools_invalidated),
        )
        self._notif_resource_updates.clear()
        self._notif_tools_invalidated.clear()
        return batch

    # ---- ClientSession message handler (transport-agnostic) ----
    def _make_message_handler(self, server_name: str) -> MessageHandlerFnT:
        async def _handler(message):
            # Only care about server-originated notifications; forward resource updates into our buffer
            try:
                # Generic extractor for method/params regardless of concrete type
                root = getattr(message, "root", message)
                method = None
                params_obj = None
                if hasattr(root, "method"):
                    method = getattr(root, "method")
                elif isinstance(root, dict):
                    method = root.get("method")
                if hasattr(root, "params"):
                    params_obj = getattr(root, "params")
                elif isinstance(root, dict):
                    params_obj = root.get("params")

                # Recognize resource update notifications by method name
                if isinstance(method, str) and (
                    "resource" in method and ("updated" in method or "change" in method)
                ):
                    uri_val = None
                    # params may be a Pydantic model or a dict
                    if params_obj is not None and hasattr(params_obj, "uri"):
                        uri_val = getattr(params_obj, "uri")
                    elif isinstance(params_obj, dict):
                        uri_val = params_obj.get("uri") or params_obj.get("resource")
                    if uri_val is not None:
                        uri = str(uri_val)
                        logger.debug("ResourceUpdatedNotification(any): %s %s", server_name, uri)
                        self.notify_resource_updated(server_name, uri)
            except Exception as e:
                logger.warning("notify_resource_updated failed: %s", e)
            await anyio.lowlevel.checkpoint()

        return _handler

    # Message handlers are installed at ClientSession construction time via
    # our open_uninitialized wrapper (see _wrap_with_handler). This currently
    # uses the private `_message_handler` hook until a public API is available.

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
    class ResourcesListRequest(BaseModel):
        server: str | None = None
        uri_prefix: str | None = None

    class ResourcesListResponse(BaseModel):
        resources: list[ResourceEntry]

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
        ResourcePartText | ResourcePartBase64,
        Field(discriminator="kind"),
    ]

    # ---- Resource helpers (typed) ----
    async def resources_list(
        self,
        req: McpManager.ResourcesListRequest,
    ) -> McpManager.ResourcesListResponse:
        items = await self.list_resources(only=[req.server] if req.server else None)
        if req.uri_prefix:
            items = [
                i
                for i in items
                if i.resource.uri and str(i.resource.uri).startswith(req.uri_prefix)
            ]
        return self.ResourcesListResponse(resources=items)

    # ---- Resource subscription helpers (pass-through to ClientSession) ----
    async def resources_subscribe(self, server: str, uri: str) -> None:
        """Subscribe to updates for a specific resource URI on a given server.

        Exposes python-sdk subscription on the underlying ClientSession.
        """
        slot = await self.ensure_open(server)
        sess = slot.session
        # python-sdk: subscribe_resource(AnyUrl | str). Some servers may not implement
        # subscriptions; treat 'Method not found' as a no-op to keep callers simple.
        try:
            await sess.subscribe_resource(uri)
        except McpError as e:
            if "Method not found" in str(e):
                logger.debug(
                    "resources_subscribe: server %s does not support subscribe; ignoring", server
                )
            else:
                raise

    async def resources_unsubscribe(self, server: str, uri: str) -> None:
        """Unsubscribe from updates for a specific resource URI on a given server.

        Exposes python-sdk unsubscription on the underlying ClientSession.
        """
        slot = await self.ensure_open(server)
        sess = slot.session
        try:
            await sess.unsubscribe_resource(uri)
        except McpError as e:
            if "Method not found" in str(e):
                logger.debug(
                    "resources_unsubscribe: server %s does not support unsubscribe; ignoring",
                    server,
                )
            else:
                raise

    @property
    def server_names(self) -> list[str]:
        """Configured server names (public API)."""
        return list(self._specs.keys())

    # ---- Structured sampling snapshot (no prompt rendering) ----
    async def sampling_snapshot(self) -> SamplingSnapshot:
        """Snapshot for model sampling: include RUNNING servers only (no failures)."""
        full = await self.servers_status()
        running = [s for s in full.servers if s.state == "running"]
        return SamplingSnapshot(ts=datetime.now(UTC).isoformat(), servers=running)

    async def servers_status(self) -> SamplingSnapshot:
        """Status for UI/diagnostics: include running and failed servers, with tools on running ones."""
        servers: list[ServerEntry] = []
        running: list[str] = []
        init_map: dict[str, InitializeResult] = {}
        for name in self.server_names:
            try:
                init_res = await self.get_server_initialize(name)
                init_map[name] = init_res
                st_cur = self._servers.get(name)
                servers.append(
                    ServerEntry(
                        name=name,
                        state="running",
                        initialize=InitializeView(
                            instructions=init_res.instructions,
                            server_info=init_res.serverInfo,
                            protocol_version=init_res.protocolVersion,
                            capabilities=init_res.capabilities,
                        ),
                        supports_resources=st_cur.supports_resources if st_cur else None,
                    )
                )
                running.append(name)
            except Exception as e:
                servers.append(
                    ServerEntry(
                        name=name,
                        state="failed",
                        error=str(e),
                        supports_resources=None,
                    )
                )
        tools_entries = await self.list_tools(only=running)
        # Attach per-server tools; UI derives counts as tools.length
        grouped_tools: dict[str, list[mcp_types.Tool]] = {}
        for t in tools_entries:
            grouped_tools.setdefault(t.server, []).append(t.tool)
        for s in servers:
            if s.state == "running":
                s.tools = grouped_tools.get(s.name, [])
        return SamplingSnapshot(ts=datetime.now(UTC).isoformat(), servers=servers)

    def slot_from_spec(self, name: str, spec: McpServerSpec) -> ServerSlotSpec:
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
        # Normalize to plain dict from Pydantic model
        data = spec.model_dump()

        transport = data.get("transport")
        if transport is None and any(k in data for k in ("command", "args", "env")):
            transport = "stdio"

        if transport == "stdio":
            params = StdioServerParameters.model_validate(data)

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
                    sess = ClientSession(
                        read_stream=read,
                        write_stream=write,
                        message_handler=self._make_message_handler(name),
                    )
                    await stack.enter_async_context(sess)
                    # Yield the uninitialized session; teardown is managed by the
                    # AsyncExitStack (no extra finally needed here).
                    yield sess

                return _ctx()

            return ServerSlotSpec(
                open_uninitialized=open_uninitialized,
                init_timeout_secs=getattr(spec, "init_timeout_secs", None),
            )

        if transport == "inproc":
            factory_path = data.get("factory")
            if not isinstance(factory_path, str) or not factory_path:
                raise ValueError(
                    "inproc transport requires 'factory' dotted path 'pkg.mod:make_server'",
                )
            # Load callable: support 'pkg.mod:func' or 'pkg.mod.func'
            if ":" in factory_path:
                mod_path, func_name = factory_path.split(":", 1)
            else:
                mod_path, func_name = factory_path.rsplit(".", 1)
            try:
                factory_mod = importlib.import_module(mod_path)
            except (ImportError, ModuleNotFoundError) as e:
                raise ValueError(
                    f"inproc factory import failed: module {mod_path!r} not importable: {e}. Hint: use 'pkg.mod:factory' or 'pkg.mod.factory'"
                ) from e
            try:
                factory = getattr(factory_mod, func_name)
            except AttributeError as e:
                raise ValueError(
                    f"inproc factory missing callable {factory_path!r}: {e}. Hint: double-check the function name after ':' or '.'"
                ) from e
            args = data.get("args") or []
            kwargs = data.get("kwargs") or {}
            if not isinstance(args, list) or not isinstance(kwargs, dict):
                raise ValueError(
                    "inproc 'args' must be list and 'kwargs' must be object/dict when provided"
                )
            server_obj = factory(*args, **kwargs)
            if not isinstance(server_obj, FastMCP):
                raise ValueError(
                    f"inproc factory returned {type(server_obj).__name__}, expected FastMCP",
                )
            return make_inproc_slot_spec(
                server_obj,
                message_handler=self._make_message_handler(name),
                init_timeout_secs=data.get("init_timeout_secs"),
            )

        if transport == "sse":
            url_val = data.get("url")
            if not isinstance(url_val, str) or not url_val:
                raise ValueError(
                    "SSE transport requires a non-empty 'url' string in spec",
                )
            headers = data.get("headers")
            # Units are seconds; fields are named with explicit unit suffixes.
            timeout_secs = data.get("timeout_secs", 5)
            sse_read_timeout_secs = data.get("sse_read_timeout_secs", 60 * 5)

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
                            timeout=timeout_secs,
                            sse_read_timeout=sse_read_timeout_secs,
                        ),
                    )
                    sess = ClientSession(
                        read_stream=read,
                        write_stream=write,
                        message_handler=self._make_message_handler(name),
                    )
                    await stack.enter_async_context(sess)
                    # Yield the uninitialized session; teardown is managed by the
                    # AsyncExitStack (no extra finally needed here).
                    yield sess

                return _ctx()

            return ServerSlotSpec(
                open_uninitialized=open_uninitialized,
                init_timeout_secs=data.get("init_timeout_secs"),
            )

        # HTTP transport not supported in this environment version; add when needed.
        raise ValueError(
            f"Unsupported or missing transport in spec for {name!r} (keys={list(data.keys())!r})",
        )

    # TODO(mpokorny): If needed later, add an 'inproc' transport that loads a dotted factory path
    # to create a FastMCP server in-proc from JSON config. For now, prefer explicit wiring in code.
    def slots_from_specs(self, specs: Mapping[str, McpServerSpec]) -> dict[str, ServerSlotSpec]:
        """Parse a mapping of name→transport spec into ServerSlotSpec entries.

        Each entry yields an UNINITIALIZED ClientSession when opened; initialization
        is performed exactly once in ServerSlotSpec.open().
        """
        return {name: self.slot_from_spec(name, spec) for name, spec in specs.items()}

    # NOTE: parse_mcp_function is provided as a top-level helper for parsing namespaced
    # MCP tool identifiers (mcp__{server}__{tool}). The instance-level resolve_function
    # method was removed: call_tool() now accepts the single namespaced identifier and
    # parses it internally. Keep parse_mcp_function exported for callers that need to
    # parse names directly (tests and event renderers).


# NotificationsBatch and ResourceUpdateEvent are defined at module level (above)
class InitializeView(BaseModel):
    instructions: str | None = None
    server_info: Any | None = None
    # Extra handshake details for UI diagnostics
    protocol_version: str | None = None
    capabilities: Any | None = None


class ServerEntry(BaseModel):
    name: str
    state: Literal["running", "failed"]
    initialize: InitializeView | None = None
    error: str | None = None
    supports_resources: bool | None = None
    tools: list[mcp_types.Tool] | None = None


class ToolEntry(BaseModel):
    server: str
    tool: mcp_types.Tool


class SamplingSnapshot(BaseModel):
    ts: str | None = None
    servers: list[ServerEntry]


# ---- Per-server worker (owns its own AsyncExitStack and session lifecycle) ----
@dataclass
class _ServerState:
    worker: Optional["_ServerWorker"] = None
    slot: Optional[ServerSlot] = None
    error: Optional[str] = None
    tools_cache: Optional[list[mcp_types.Tool]] = None
    spec: Optional[ServerSlotSpec] = None
    resource_versions: dict[str, int] = field(default_factory=dict)
    inflight_ids: set[int] = field(default_factory=set)
    init: Optional[InitializeResult] = None
    supports_resources: Optional[bool] = None


class _ServerWorker:
    def __init__(self, manager: McpManager, name: str, spec: ServerSlotSpec) -> None:  # type: ignore[name-defined]
        self.manager = manager
        self.name = name
        self.spec = spec
        self.task: Optional[asyncio.Task] = None
        self.ready: asyncio.Event = asyncio.Event()
        self.stop_ev: asyncio.Event = asyncio.Event()
        self.slot: Optional[ServerSlot] = None
        self.error: Optional[str] = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self.stop_ev.set()

    async def wait_ready(self) -> None:
        await self.ready.wait()

    async def _run(self) -> None:
        try:
            logger.info("ServerWorker[%s]: starting", self.name)
            try:
                print(f"[ServerWorker] starting: {self.name}")
            except Exception:
                pass
            async with AsyncExitStack() as stack:
                # Open and initialize the session under this task's stack
                logger.info("ServerWorker[%s]: opening slot (initialize)", self.name)
                try:
                    print(f"[ServerWorker] opening slot (initialize): {self.name}")
                except Exception:
                    pass
                slot = await self.spec.open(stack)
                logger.info(
                    "ServerWorker[%s]: initialize ok; supports_resources=%s",
                    self.name,
                    self.manager._supports_resources_from_init(slot.init_result),
                )
                try:
                    print(f"[ServerWorker] initialize ok: {self.name}")
                except Exception:
                    pass
                # Prime server-side session capture/flush (e.g., NotifyingFastMCP)
                try:
                    await asyncio.wait_for(slot.session.list_tools(), timeout=2)
                except Exception:
                    # Best-effort priming; ignore failures/timeouts
                    pass
                # Wrap session to track outgoing request ids for cancellation
                self.manager._wrap_session(slot.session, self.name)
                self.slot = slot
                # Publish realized slot for manager fast-path reads
                lock = self.manager._lock
                assert lock is not None
                async with lock:
                    st = self.manager._state(self.name)
                    st.slot = slot
                    st.init = slot.init_result
                    st.supports_resources = self.manager._supports_resources_from_init(
                        slot.init_result
                    )
                self.ready.set()
                # Wait until asked to stop
                logger.info("ServerWorker[%s]: ready; waiting for stop", self.name)
                try:
                    print(f"[ServerWorker] ready; waiting for stop: {self.name}")
                except Exception:
                    pass
                await self.stop_ev.wait()
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.ready.set()
            logger.exception("ServerWorker[%s]: error during run: %s", self.name, e)
