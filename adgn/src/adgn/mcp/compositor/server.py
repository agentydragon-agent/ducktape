from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import Enum, StrEnum, auto
import logging
import re
import sys
import warnings

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
from mcp import types as mcp_types

from adgn.mcp.compositor.mount import Mount
from adgn.mcp.snapshots import (
    FailedServerEntry,
    InitializingServerEntry,
    RunningServerEntry,
    SamplingSnapshot,
    ServerEntry,
)

logger = logging.getLogger(__name__)


class ChildNotificationHandler(MessageHandler):
    """Message handler that forwards notifications to compositor with origin attribution."""

    def __init__(self, compositor: Compositor, server_name: str) -> None:
        self._compositor = compositor
        self._server_name = server_name

    async def on_resource_list_changed(self, message: mcp_types.ResourceListChangedNotification) -> None:
        self._compositor._pending_resource_list_changes.add(self._server_name)
        # No forwarding here; child client handles forwarding via proxy
        await self._compositor._notify_resource_list_change(self._server_name)

    async def on_resource_updated(self, message: mcp_types.ResourceUpdatedNotification) -> None:
        # Forward to listeners with origin attribution
        await self._compositor._notify_resource_updated(self._server_name, str(message.params.uri))


class CompositorState(Enum):
    """Compositor lifecycle states.

    Transitions:
    - CREATED → ACTIVE (on first __aenter__)
    - ACTIVE → CLOSED (on __aexit__)
    - CREATED/ACTIVE → CLOSED (on explicit close())

    Invalid transitions:
    - ACTIVE → ACTIVE (double-enter, raises RuntimeError)
    - CLOSED → anything (closed is terminal)
    """

    CREATED = auto()  # Constructed but not entered
    ACTIVE = auto()  # Inside async with block
    CLOSED = auto()  # Cleanup completed, terminal state


class MountEvent(StrEnum):
    MOUNTED = "mounted"
    UNMOUNTED = "unmounted"
    STATE = "state"


class Compositor(FastMCP):
    """Aggregates upstream MCP servers under a single FastMCP surface.

    MUST be used as async context manager:
        async with Compositor() as comp:
            await comp.mount_server(...)
            async with Client(comp) as client:
                # Use client
                ...
        # All non-pinned servers cleaned up here

    - Namespaces tools as {server}_{tool}
    - Reuses persistent upstream sessions per mount
    - Relays resource updates as notifications
    - Exposes a Python management API (mount/unmount); state is served via the
      separate compositor_meta server resources
    """

    def __init__(self, name: str = "compositor", *, instructions: str | None = None) -> None:
        super().__init__(name=name, instructions=instructions)

        # State machine (replaces _context_manager_entered/_context_manager_exited)
        self._state = CompositorState.CREATED
        self._state_lock = asyncio.Lock()

        # Mounts and listeners
        self._mounts: dict[str, Mount] = {}
        self._mount_lock = asyncio.Lock()
        self._mount_listeners: list[Callable[[str, MountEvent], Awaitable[None] | None]] = []

        # Resource change tracking
        self._pending_resource_list_changes: set[str] = set()
        self._resource_list_change_listeners: list[Callable[[str], Awaitable[None] | None]] = []
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
        async with self._mount_lock:
            items = list(self._mounts.items())
        per_name: dict[str, ServerEntry] = {}
        tool_tasks: dict[str, asyncio.Task[list[mcp_types.Tool]]] = {}

        for name, mount in items:
            # Check mount state
            if mount.is_failed:
                exc = mount.exception
                error_msg = str(exc) if exc else "Mount failed"
                per_name[name] = FailedServerEntry(error=error_msg)
                continue

            if not mount.is_active:
                per_name[name] = InitializingServerEntry()
                continue

            try:
                # Get initialize result from child client
                client = mount.child_client
                init = client.initialize_result

                # If we don't have init result, that's a failure
                if init is None:
                    per_name[name] = FailedServerEntry(error="No initialize result available")
                    continue

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
        async with self._mount_lock:
            return {k: v.spec for k, v in self._mounts.items() if v.spec is not None}

    # No resource helper methods: resources are aggregated and served via the
    # mounted proxy. Callers should use a client connected to this Compositor
    # (or the gateway) to list/read resources.

    # ---- Management API (Python-only) --------------------------------------

    async def mount_server(
        self, name: str, spec: MCPServerTypes, prefix: str | None = None, *, pinned: bool = False
    ) -> None:
        """Mount server from MCP config (stdio, HTTP, etc).

        Exception-safe: if mount fails, no server is registered and no resources leak.

        Args:
            name: Server name (used in tool prefixes: {name}_{tool})
            spec: Server configuration (StdioMCPServer, RemoteMCPServer, etc)
            prefix: Optional prefix (defaults to name)
            pinned: If True, server won't be unmounted on close()

        Raises:
            RuntimeError: If state is CLOSED
            ValueError: If name is invalid or already mounted
        """
        # Check state
        async with self._state_lock:
            if self._state == CompositorState.CLOSED:
                raise RuntimeError(f"Cannot mount server - compositor '{self.name}' is closed")

        # Validate name
        if not name or not re.match(r"^[a-z][a-z0-9_]*$", name):
            raise ValueError(f"Invalid server name: {name!r}")

        # Prefix equals server name (semantic only)
        prefix = prefix or name

        # Check for duplicate under lock
        async with self._mount_lock:
            if name in self._mounts:
                raise ValueError(f"Server '{name}' is already mounted")

        # Create mount and setup (exception-safe internally)
        mount = Mount(name=name, pinned=pinned, spec=spec)
        await mount.setup_external(spec, self._fm_transport_from_spec, lambda n: ChildNotificationHandler(self, n))

        # Register the mount (under lock)
        async with self._mount_lock:
            self._mounts[name] = mount

        # Mount proxy on FastMCP surface
        if mount.is_active:
            self.mount(mount.proxy, prefix=name)
            await self._notify_mount_listeners(name, MountEvent.STATE)
            await self._notify_mount_listeners(name, MountEvent.MOUNTED)
        else:
            # Mount failed but is registered (for status reporting)
            await self._notify_mount_listeners(name, MountEvent.STATE)

    async def mount_inproc(
        self, name: str, server: FastMCP, prefix: str | None = None, *, pinned: bool = False
    ) -> None:
        """Mount in-process FastMCP server.

        Exception-safe: if mount fails, no server is registered and no resources leak.

        Args:
            name: Server name (used in tool prefixes: {name}_{tool})
            server: FastMCP server instance
            prefix: Optional prefix (defaults to name)
            pinned: If True, server won't be unmounted on close()

        Raises:
            RuntimeError: If state is CLOSED
            ValueError: If name is invalid or already mounted
        """
        # Check state
        async with self._state_lock:
            if self._state == CompositorState.CLOSED:
                raise RuntimeError(f"Cannot mount server - compositor '{self.name}' is closed")

        # Validate name
        if not name or not re.match(r"^[a-z][a-z0-9_]*$", name):
            raise ValueError(f"Invalid server name: {name!r}")

        # Prefix equals server name (semantic only)
        prefix = prefix or name

        # Check for duplicate under lock
        async with self._mount_lock:
            if name in self._mounts:
                raise ValueError(f"Server '{name}' is already mounted")

        # Create mount and setup (exception-safe internally)
        mount = Mount(name=name, pinned=pinned, spec=None)
        await mount.setup_inproc(server, lambda n: ChildNotificationHandler(self, n))

        # Register the mount (under lock)
        async with self._mount_lock:
            self._mounts[name] = mount

        # Mount proxy on FastMCP surface
        if mount.is_active:
            self.mount(mount.proxy, prefix=name)
            await self._notify_mount_listeners(name, MountEvent.STATE)
            await self._notify_mount_listeners(name, MountEvent.MOUNTED)
        else:
            # Mount failed but is registered (for status reporting)
            await self._notify_mount_listeners(name, MountEvent.STATE)

    async def unmount_server(self, name: str) -> None:
        """Unmount a specific server.

        Exception-safe: cleanup always attempted, mount always removed from dict.

        Args:
            name: Server name

        Raises:
            RuntimeError: If server is pinned or compositor is closed
            ValueError: If server not found
        """
        if not name:
            raise ValueError("server name cannot be empty")

        # Defensive check: prevent unmount when closed
        async with self._state_lock:
            if self._state == CompositorState.CLOSED:
                raise RuntimeError(f"Cannot unmount server - compositor '{self.name}' is closed")

        # Get mount under lock
        async with self._mount_lock:
            mount = self._mounts.get(name)

            if mount is None:
                raise ValueError(f"Server '{name}' is not mounted")

            if mount.pinned:
                raise RuntimeError(
                    f"Cannot unmount pinned server '{name}'. Pinned servers remain for the compositor's lifetime."
                )

        # Defensive check: warn if mount is in unexpected state
        if not mount.is_active and not mount.is_failed:
            logger.warning(
                f"Unmounting server '{name}' in unexpected state: {mount.state.name}. Cleanup will proceed anyway."
            )

        # Cleanup (exception-safe, idempotent)
        # Always remove from dict even if cleanup fails
        try:
            await mount.cleanup()
        except Exception as e:
            logger.exception(f"Error cleaning up mount '{name}' (server will still be unmounted)", exc_info=e)

        # Remove from dict (always, even if cleanup failed)
        async with self._mount_lock:
            self._mounts.pop(name, None)

        # Notify listeners
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
        """Enter context. Returns self (NOT a separate Handle type).

        Raises:
            RuntimeError: If already entered or closed
        """
        async with self._state_lock:
            if self._state == CompositorState.ACTIVE:
                raise RuntimeError(
                    f"Compositor '{self.name}' is already in an active context manager! "
                    "Cannot enter the same compositor twice."
                )
            if self._state == CompositorState.CLOSED:
                raise RuntimeError(f"Compositor '{self.name}' is already closed. Cannot reuse a closed compositor.")

            self._state = CompositorState.ACTIVE

        return self  # Return self, NOT a separate handle

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context, cleanup all non-pinned servers.

        Always updates state to CLOSED, even if cleanup fails.
        """
        try:
            await self.close()
        finally:
            async with self._state_lock:
                self._state = CompositorState.CLOSED

        return False  # Don't suppress exceptions

    async def close(self):
        """Cleanup all non-pinned servers. Exception-safe.

        Logs warnings for per-server failures but continues cleanup.
        Safe to call multiple times (idempotent).
        """
        # Defensive check: warn if called when already closed
        if self._state == CompositorState.CLOSED:
            logger.debug(f"Compositor '{self.name}' close() called when already CLOSED (idempotent, but unexpected)")
            return

        # Snapshot non-pinned servers under lock
        async with self._mount_lock:
            names = [name for name, mount in self._mounts.items() if not mount.pinned]

        # Defensive check: detect if we have unexpected mounts
        if self._state == CompositorState.CREATED and names:
            logger.warning(
                f"Compositor '{self.name}' close() called in CREATED state "
                f"but has {len(names)} non-pinned server(s). This suggests "
                "servers were mounted without entering context manager."
            )

        # Unmount each server (exception-safe)
        for name in names:
            try:
                await self.unmount_server(name)
            except Exception as e:
                logger.exception(f"Failed to unmount server '{name}' during cleanup", exc_info=e)
                # Continue cleanup of other servers

    def __del__(self):
        """Warn if compositor is garbage collected without proper cleanup.

        This detects container leaks at development time by catching compositors
        that were created without using 'async with Compositor() as comp:'.
        """
        # Check if we have unclosed non-pinned mounts
        if not hasattr(self, "_mounts") or not self._mounts:
            return

        non_pinned = [name for name, mount in self._mounts.items() if not mount.pinned]
        if not non_pinned:
            return

        # Determine the specific problem
        state = getattr(self, "_state", None)
        if state == CompositorState.CREATED:
            problem = "was never used as context manager"
            hint = "ALWAYS use: async with Compositor() as comp:"
        elif state == CompositorState.ACTIVE:
            problem = "entered but never exited"
            hint = "Did the async context manager fail to exit?"
        elif state == CompositorState.CLOSED:
            problem = "has unclosed servers after exit"
            hint = "This may indicate a cleanup failure in close()"
        else:
            problem = "has invalid state"
            hint = "Internal error - state tracking broken"

        msg = (
            f"\nCOMPOSITOR LEAK: '{self.name}' {problem}!\n"
            f"  Still has {len(non_pinned)} server(s): {non_pinned}\n"
            f"  This will leak Docker containers!\n\n"
            f"  {hint}\n"
        )

        warnings.warn(msg, ResourceWarning, stacklevel=2)
        print(msg, file=sys.stderr)

    # Python-only mount listing and server_status removed — prefer resources via compositor_meta

    # ---- Aggregated surface (protocol handlers) ----------------------------
    # Note: inherit FastMCP protocol handlers directly; no overrides required.

    # Resource operations are not overridden; FastMCP mount handles routing

    # ---- Internals ----------------------------------------------------------
    async def _mount_names(self) -> list[str]:
        async with self._mount_lock:
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

        Raises:
            ValueError: If server not found
            RuntimeError: If server not active
        """
        mount = self._mounts.get(name)
        if mount is None:
            raise ValueError(f"Server '{name}' is not mounted")

        # Use mount's property which validates state
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


async def build_compositor(cfg: MCPConfig, *, name: str = "compositor", instructions: str | None = None) -> Compositor:
    """Create a Compositor and attach mounts from typed specs.

    The returned server exposes an aggregated MCP surface; caller is responsible
    for running it (e.g., via run_streamable_http_async()).

    Note: The returned compositor is NOT entered as a context manager.
    Caller must use 'async with comp:' if cleanup is needed.
    """
    comp = Compositor(name=name, instructions=instructions)
    await comp.mount_servers_from_config(cfg)
    return comp
