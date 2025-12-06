from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import logging

from fastmcp.client import Client
from fastmcp.client.messages import MessageHandler
from fastmcp.client.transports import ClientTransport, StdioTransport, StreamableHttpTransport
from fastmcp.mcp_config import (
    MCPConfig,
    MCPServerTypes,
    RemoteMCPServer,
    StdioMCPServer,
    TransformingRemoteMCPServer,
    TransformingStdioMCPServer,
)
from fastmcp.server import FastMCP
from fastmcp.server.proxy import FastMCPProxy
from mcp import types as mcp_types

from adgn.mcp.snapshots import (
    FailedServerEntry,
    InitializingServerEntry,
    RunningServerEntry,
    SamplingSnapshot,
    ServerEntry,
)

logger = logging.getLogger(__name__)


# No extra JSON alias needed in this module


@dataclass
class _MountState:
    name: str
    spec: MCPServerTypes | None
    error: str | None = None
    proxy: FastMCPProxy | None = None
    cached_init: mcp_types.InitializeResult | None = None
    # No separate monitor client; message handler is attached to the primary client
    # Persistent child client to keep a session open for notifications/subscriptions
    child_client: Client | None = None
    stack: AsyncExitStack | None = None
    pinned: bool = False


class MountEvent(StrEnum):
    MOUNTED = "mounted"
    UNMOUNTED = "unmounted"
    STATE = "state"


class Compositor(FastMCP):
    """Aggregates upstream MCP servers under a single FastMCP surface.

    - Namespaces tools as {server}_{tool}
    - Reuses persistent upstream sessions per mount
    - Relays resource updates as notifications
    - Exposes a Python management API (mount/unmount); state is served via the
      separate compositor_meta server resources
    """

    def __init__(self, name: str = "compositor", *, instructions: str | None = None, eager_open: bool = True) -> None:
        super().__init__(name=name, instructions=instructions)
        # Internal behavior flags
        self._eager = eager_open
        # Mounts (typed specs or in-proc servers)
        self._mounts: dict[str, _MountState] = {}
        self._lock = asyncio.Lock()
        # Mount lifecycle listeners: callbacks invoked on mount/unmount/state events
        # Callable signature: (name: str, action: MountEvent) -> Optional[Awaitable[None]]
        self._mount_listeners: list[Callable[[str, MountEvent], Awaitable[None] | None]] = []
        # Servers that reported resource list changes (pending broadcast)
        self._pending_resource_list_changes: set[str] = set()
        # Resource list change listeners (server-scoped)
        # Callable signature: (name: str) -> Optional[Awaitable[None]]
        self._resource_list_change_listeners: list[Callable[[str], Awaitable[None] | None]] = []
        # Resource-updated event listeners (server-scoped, with URI)
        # Callable signature: (name: str, uri: str) -> Optional[Awaitable[None]]
        self._resource_updated_listeners: list[Callable[[str, str], Awaitable[None] | None]] = []

        # Compositor metadata resources are exposed via the separate 'compositor_meta' server.

    # ---- Public child client accessor -------------------------------------

    def add_mount_listener(self, cb: Callable[[str, MountEvent], Awaitable[None] | None]) -> None:
        """Register a callback invoked on mount lifecycle changes.

        Callback signature: (name: str, action: MountEvent) where action is one of
        MountEvent.MOUNTED | MountEvent.UNMOUNTED | MountEvent.STATE.
        """
        self._mount_listeners.append(cb)

    async def _notify_mount_listeners(self, name: str, action: MountEvent) -> None:
        for cb in list(self._mount_listeners):
            res = cb(name, action)
            if asyncio.iscoroutine(res):
                await res

    def add_resource_list_change_listener(self, cb: Callable[[str], Awaitable[None] | None]) -> None:
        """Register a callback invoked when a child reports resources/list_changed.

        Callback signature: (name: str) where name is the origin server.
        """
        self._resource_list_change_listeners.append(cb)

    async def _notify_resource_list_change(self, name: str) -> None:
        for cb in list(self._resource_list_change_listeners):
            res = cb(name)
            if asyncio.iscoroutine(res):
                await res

    def add_resource_updated_listener(self, cb: Callable[[str, str], Awaitable[None] | None]) -> None:
        """Register a callback invoked when a child reports resources/updated.

        Callback signature: (name: str, uri: str) where name is the origin
        server and uri is the raw (unprefixed) resource URI from the child.
        """
        self._resource_updated_listeners.append(cb)

    async def _notify_resource_updated(self, name: str, uri: str) -> None:
        for cb in list(self._resource_updated_listeners):
            res = cb(name, uri)
            if asyncio.iscoroutine(res):
                await res

    # ---- Child notifications capture (origin attribution) -----------------
    class _ChildHandler(MessageHandler):
        def __init__(self, owner: Compositor, name: str) -> None:
            self._compositor = owner
            self._name = name

        async def on_resource_list_changed(self, message: mcp_types.ResourceListChangedNotification) -> None:
            self._compositor._pending_resource_list_changes.add(self._name)
            # No forwarding here; child client handles forwarding via proxy
            await self._compositor._notify_resource_list_change(self._name)

        async def on_resource_updated(self, message: mcp_types.ResourceUpdatedNotification) -> None:
            # Forward to listeners with origin attribution
            await self._compositor._notify_resource_updated(self._name, str(message.params.uri))

    def pop_recent_resource_list_changes(self) -> list[str]:
        """Return and clear servers that recently reported resource list changes."""
        names = sorted(self._pending_resource_list_changes)
        self._pending_resource_list_changes.clear()
        return names

    # No child_* helpers; callers should use server_entries()/sampling_snapshot()

    async def server_entries(self) -> dict[str, ServerEntry]:
        """Return per-child status entries keyed by child name.

        Entries are discriminated-union ServerEntry values keyed by mount name.
        """
        # Phase 1: capture init results and schedule tool enumeration concurrently
        async with self._lock:
            items = list(self._mounts.items())
        per_name: dict[str, ServerEntry] = {}
        tool_tasks: dict[str, asyncio.Task[list[mcp_types.Tool]]] = {}
        for name, mount in items:
            # Early bailout for in-process mounts (no proxy)
            if mount.proxy is None:
                per_name[name] = InitializingServerEntry()
                continue

            try:
                init = mount.cached_init
                if init is None:
                    client_factory = mount.proxy.client_factory
                    client = client_factory()
                    async with client as c:
                        init = c.initialize_result
                        mount.cached_init = init

                # Schedule list_tools via proxy client for parallel enumeration
                async def _list_tools_via_client(cf):
                    cli = cf()
                    async with cli:
                        return await cli.list_tools()

                tool_tasks[name] = asyncio.create_task(_list_tools_via_client(mount.proxy.client_factory))
                per_name[name] = RunningServerEntry(initialize=init, tools=[])
            except Exception as e:
                per_name[name] = FailedServerEntry(error=f"{type(e).__name__}: {e}")

        # Phase 2: resolve tool enumeration in parallel with structured concurrency
        async def _handle_tools(name: str, task: asyncio.Task, entry: RunningServerEntry):
            try:
                tools = await task
                per_name[name] = RunningServerEntry(initialize=entry.initialize, tools=tools)
            except Exception as e:
                per_name[name] = FailedServerEntry(error=f"{type(e).__name__}: {e}")

        async with asyncio.TaskGroup() as tg:
            for name, task in tool_tasks.items():
                entry = per_name[name]
                assert isinstance(entry, RunningServerEntry), (
                    f"Expected RunningServerEntry for {name}, got {type(entry)}"
                )
                tg.create_task(_handle_tools(name, task, entry))

        return per_name

    async def sampling_snapshot(self) -> SamplingSnapshot:
        """Return a SamplingSnapshot mirroring the manager's shape, aggregated over children."""
        entries_map = await self.server_entries()
        return SamplingSnapshot(ts=datetime.now(UTC).isoformat(), servers=entries_map)

    async def mount_specs(self) -> dict[str, MCPServerTypes]:
        """Return a snapshot of current mount specs keyed by name.

        Only includes spec-based mounts; in-process mounts (spec=None) are excluded.
        """
        async with self._lock:
            return {k: v.spec for k, v in self._mounts.items() if v.spec is not None}

    # No resource helper methods: resources are aggregated and served via the
    # mounted proxy. Callers should use a client connected to this Compositor
    # (or the gateway) to list/read resources.

    # ---- Management API (Python-only) --------------------------------------

    async def mount_server(self, name: str, spec: MCPServerTypes, prefix: str | None = None) -> None:
        if not name or "__" in name:
            raise ValueError("invalid mount name; must be non-empty and not contain '__'")
        # Prefix equals server name (semantic only); actual namespacing applied per tool mount
        prefix = prefix or name
        async with self._lock:
            if name in self._mounts:
                raise ValueError(f"server '{name}' already mounted; detach first")
            mount = _MountState(name=name, spec=spec)
            self._mounts[name] = mount
        transport = self._fm_transport_from_spec(spec)
        # Primary client with child-aware message handler for origin tagging
        base_client = Client(transport, message_handler=Compositor._ChildHandler(self, name))
        proxy = FastMCP.as_proxy(base_client)
        # Ensure proxy uses the persistent child client session (not fresh per request)
        proxy.client_factory = lambda: base_client
        mount.proxy = proxy
        # Start a persistent session for notifications/subscriptions immediately
        stack = AsyncExitStack()
        await stack.enter_async_context(base_client)
        mount.stack = stack
        mount.child_client = base_client
        # Cache initialize result and notify state (always on mount)
        mount.cached_init = base_client.initialize_result
        await self._notify_mount_listeners(name, MountEvent.STATE)
        # Mount using a prefix that results in names '{server}_{tool}'
        self.mount(proxy, prefix=name)
        await self._notify_mount_listeners(name, MountEvent.MOUNTED)

    async def mount_inproc(self, name: str, app: FastMCP, prefix: str | None = None, *, pinned: bool = False) -> None:
        """Mount a local FastMCP server directly (no HTTP/stdio), keeping a client for status."""
        if not name or "__" in name:
            raise ValueError("invalid mount name; must be non-empty and not contain '__'")
        prefix = prefix or name
        async with self._lock:
            if name in self._mounts:
                raise ValueError(f"server '{name}' already mounted; detach first")
            mount = _MountState(name=name, spec=None)
            self._mounts[name] = mount
        # Primary client with child-aware message handler for origin tagging
        base_client = Client(app, message_handler=Compositor._ChildHandler(self, name))
        proxy = FastMCP.as_proxy(base_client)
        mount.proxy = proxy
        # Start a persistent session for notifications/subscriptions immediately
        stack = AsyncExitStack()
        await stack.enter_async_context(base_client)
        mount.stack = stack
        mount.child_client = base_client

        # Ensure proxy uses the persistent child client session
        proxy.client_factory = lambda: base_client
        self.mount(proxy, prefix=name)
        # Cache initialize result and notify state (always on mount)
        mount.cached_init = base_client.initialize_result
        mount.pinned = pinned
        await self._notify_mount_listeners(name, MountEvent.STATE)
        await self._notify_mount_listeners(name, MountEvent.MOUNTED)

    async def unmount_server(self, name: str) -> None:
        if not name:
            raise ValueError("server name cannot be empty")
        # Prevent unmount of pinned servers
        async with self._lock:
            mount = self._mounts.get(name)
            if mount is not None and mount.pinned:
                raise RuntimeError(f"server '{name}' is pinned and cannot be unmounted")
            mount = self._mounts.pop(name, None)
        # Stop persistent client (if any)
        if mount is not None:
            try:
                if mount.stack is not None:
                    await mount.stack.aclose()
            finally:
                mount.child_client = None
                mount.stack = None
        await self._notify_mount_listeners(name, MountEvent.UNMOUNTED)

    async def mount_servers_from_config(
        self, config: MCPConfig, *, on_error: str = "raise"
    ) -> dict[str, Exception | None]:
        """Mount multiple servers from config in parallel.

        Args:
            config: MCPConfig object with mcpServers dict
            on_error: How to handle mount errors:
                - "raise": Raise on first error (default)
                - "collect": Continue mounting others, return errors dict

        Returns:
            Dict mapping server name to error (None if successful)
        """
        servers = config.mcpServers
        if not servers:
            return {}

        # Mount all servers in parallel
        async def _mount_one(name: str, spec: MCPServerTypes) -> tuple[str, Exception | None]:
            try:
                await self.mount_server(name, spec)
                return (name, None)
            except Exception as e:
                if on_error == "raise":
                    raise
                return (name, e)

        results = await asyncio.gather(*[_mount_one(name, spec) for name, spec in servers.items()])
        return dict(results)

    # ---- Lifecycle management (async context manager) ---------------------

    async def __aenter__(self):
        """Support async context manager protocol."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup all non-pinned servers on exit."""
        await self.close()
        return False

    async def close(self):
        """Unmount all non-pinned servers and cleanup their resources.

        Pinned servers (e.g., compositor_meta, resources) are left mounted.
        Logs warnings for cleanup failures but does not raise.
        """
        async with self._lock:
            names = [name for name, mount in self._mounts.items() if not mount.pinned]

        for name in names:
            try:
                await self.unmount_server(name)
            except Exception as e:
                logger.warning(f"Failed to unmount server '{name}' during close: {e}")

    # Python-only mount listing and server_status removed — prefer resources via compositor_meta

    # ---- Aggregated surface (protocol handlers) ----------------------------
    # Note: inherit FastMCP protocol handlers directly; no overrides required.

    # Resource operations are not overridden; FastMCP mount handles routing

    # ---- Internals ----------------------------------------------------------
    async def _mount_names(self) -> list[str]:
        async with self._lock:
            return list(self._mounts.keys())

    # ---- Slot factory (transport-agnostic) ---------------------------------
    # No manual slot construction; composition is done via FastMCP proxy mounts

    def _fm_transport_from_spec(self, spec: MCPServerTypes) -> ClientTransport:
        # Use FastMCP's typed server config classes
        if isinstance(spec, RemoteMCPServer | TransformingRemoteMCPServer):
            headers = dict(spec.headers or {})
            if spec.auth:
                headers.setdefault("Authorization", f"Bearer {spec.auth}")
            return StreamableHttpTransport(spec.url, headers=headers)
        if isinstance(spec, StdioMCPServer | TransformingStdioMCPServer):
            return StdioTransport(spec.command, args=list(spec.args or []), env=spec.env, cwd=spec.cwd)
        raise ValueError("unsupported transport for fastmcp client")

    # No URI decoding helpers needed; rely on FastMCP mount semantics

    def get_child_client(self, name: str) -> Client:
        """Return the persistent child client for a mounted server.

        The returned client maintains a long-lived session. Callers MAY use
        `async with client:` to temporarily borrow the session; exiting the
        context will not close the underlying persistent session.
        """
        mount = self._mounts.get(name)
        if mount is None or mount.child_client is None:
            raise ValueError(f"unknown server '{name}' or no monitor client")
        return mount.child_client

    async def read_resource_contents(
        self, uri: mcp_types.AnyUrl
    ) -> list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents]:
        """Read resource contents, converting from FastMCP's internal types to MCP protocol types.

        Used by resources server to avoid client dependency. FastMCP's internal _read_resource_mcp
        returns mcp.server.lowlevel.helper_types.ReadResourceContents which must be converted to
        proper MCP protocol types (TextResourceContents | BlobResourceContents).
        """
        raw_contents = await self._read_resource_mcp(uri)
        # Convert FastMCP's internal ReadResourceContents to MCP protocol types
        return [
            mcp_types.BlobResourceContents(
                uri=uri, mimeType=c.mime_type, blob=base64.b64encode(c.content).decode("ascii")
            )
            if isinstance(c.content, bytes)
            else mcp_types.TextResourceContents(uri=uri, mimeType=c.mime_type, text=c.content)
            for c in raw_contents
        ]


async def build_compositor(
    cfg: MCPConfig, *, name: str = "compositor", instructions: str | None = None, eager_open: bool = True
) -> Compositor:
    """Create a Compositor and attach mounts from typed specs.

    The returned server exposes an aggregated MCP surface; caller is responsible
    for running it (e.g., via run_streamable_http_async()).
    """
    comp = Compositor(name=name, instructions=instructions, eager_open=eager_open)
    await comp.mount_servers_from_config(cfg)
    return comp
