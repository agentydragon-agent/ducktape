from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

from fastmcp.client import Client
from fastmcp.client.messages import MessageHandler
from fastmcp.server.server import has_resource_prefix
from mcp import types as mcp_types

from adgn.agent.notifications.types import NotificationsBatch, ResourcesServerNotice
from adgn.mcp.compositor.server import Compositor

logger = logging.getLogger(__name__)


class _ResourceNotificationHandler(MessageHandler):
    """Message handler that forwards resource notifications to NotificationsBuffer."""

    def __init__(self, owner: NotificationsBuffer) -> None:
        self._buffer = owner

    # Override with narrower types than base MessageHandler (which accepts Any)
    async def on_resource_updated(self, message: mcp_types.ResourceUpdatedNotification) -> None:
        await self._buffer._on_updated(message)

    async def on_resource_list_changed(self, message: mcp_types.ResourceListChangedNotification) -> None:
        await self._buffer._on_list_changed(message)


class NotificationsBuffer:
    """Capture MCP resource notifications and expose a simple poll/peek API.

    - Attaches to a FastMCP Client via `message_handler` when the client is created.
    - Groups updates by server with deduplicated URIs using frozenset.
    - Server names are derived via Compositor mount prefixes when possible; otherwise set to 'unknown'.
    - Hooks can be registered to react to updates (e.g., push UI snapshots).
    """

    def __init__(self, *, client: Client | None = None, compositor: Compositor) -> None:
        self._client = client
        self._compositor = compositor
        # Per-server updates (mutable sets during accumulation, converted to frozenset on poll/peek)
        self._updates: dict[str, set[str]] = {}
        self._list_changed: set[str] = set()
        self._hooks: list[Callable[[], Awaitable[None]]] = []
        self.handler: MessageHandler = _ResourceNotificationHandler(self)
        # Subscribe to compositor-level notifications when available so we don't
        # rely solely on client message forwarding (which may be disabled for
        # in-proc mounts).
        self._compositor.add_resource_updated_listener(self._on_resource_listener)
        self._compositor.add_list_changed_listener(self._on_list_listener)
        # Capture any pending list-changed signals emitted before the buffer attached
        self._list_changed.update(self._compositor.pop_recent_list_changed())

    def add_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._hooks.append(hook)

    def clear_hooks(self) -> None:
        self._hooks.clear()

    def poll(self) -> NotificationsBatch:
        """Poll and clear buffered notifications, returning grouped batch."""
        resources = self._build_resources()
        self._updates.clear()
        self._list_changed.clear()
        return NotificationsBatch(resources=resources)

    def peek(self) -> NotificationsBatch:
        """Peek at buffered notifications without clearing them."""
        resources = self._build_resources()
        return NotificationsBatch(resources=resources)

    def _build_resources(self) -> dict[str, ResourcesServerNotice]:
        """Build the grouped resources structure from current buffer state."""
        resources: dict[str, ResourcesServerNotice] = {}
        # Add servers with updated resources
        for server, uris in self._updates.items():
            resources[server] = ResourcesServerNotice(
                updated=frozenset(uris),
                list_changed=server in self._list_changed
            )
        # Add servers that only have list_changed (no updated URIs)
        for server in self._list_changed:
            if server not in resources:
                resources[server] = ResourcesServerNotice(
                    updated=frozenset(),
                    list_changed=True
                )
        return resources

    async def _on_updated(self, message: mcp_types.ResourceUpdatedNotification) -> None:
        # Add URI to the server's update set
        uri_str = str(message.params.uri)
        server = await self._derive_server(uri_str)
        self._updates.setdefault(server, set()).add(uri_str)
        await self._run_hooks()

    async def _on_list_changed(self, message: mcp_types.ResourceListChangedNotification) -> None:
        # Attribute origin using compositor-captured child notifications when available
        names = list(self._compositor.pop_recent_list_changed())
        self._list_changed.update(names)
        await self._run_hooks()

    async def _derive_server(self, uri: str) -> str:
        # Do not guess on format. Require compositor to provide the resource prefix format;
        # if not available, fail loudly. TODO: consider exposing a dedicated MCP method on
        # the compositor to translate URIs → origin server deterministically.
        specs = await self._compositor.mount_specs()
        fmt = self._compositor.resource_prefix_format
        for name in sorted(specs.keys()):
            name_str = str(name)
            if has_resource_prefix(uri, name_str, fmt):
                return name_str
        return "unknown"

    async def _on_resource_listener(self, name: str, uri: str) -> None:
        self._updates.setdefault(name, set()).add(uri)
        await self._run_hooks()

    async def _on_list_listener(self, name: str) -> None:
        self._list_changed.add(name)
        await self._run_hooks()

    async def _run_hooks(self) -> None:
        if not self._hooks:
            return
        for hook in list(self._hooks):
            try:
                await hook()
            except Exception:
                logger.debug("notifications hook failed", exc_info=True)
