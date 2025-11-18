from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

from fastmcp.client import Client
from fastmcp.client.messages import MessageHandler
from fastmcp.server.server import has_resource_prefix
from mcp import types as mcp_types

from adgn.agent.notifications.types import NotificationsBatch, ResourceUpdateEvent
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
    - Groups updates as ResourceUpdateEvent(server, uri). Server is derived via
      Compositor mount prefixes when possible; otherwise set to 'unknown'.
    - Hooks can be registered to react to updates (e.g., push UI snapshots).
    """

    def __init__(self, *, client: Client | None = None, compositor: Compositor) -> None:
        self._client = client
        self._compositor = compositor
        self._updates: list[ResourceUpdateEvent] = []
        self._list_changed: set[str] = set()
        self._raw: list[mcp_types.ResourceUpdatedNotification | mcp_types.ResourceListChangedNotification] = []
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
        batch = NotificationsBatch(
            resources_updated=list(self._updates), resource_list_changed=sorted(self._list_changed), raw=list(self._raw)
        )
        self._updates.clear()
        self._list_changed.clear()
        self._raw.clear()
        return batch

    def peek(self) -> NotificationsBatch:
        return NotificationsBatch(
            resources_updated=list(self._updates), resource_list_changed=sorted(self._list_changed), raw=list(self._raw)
        )

    async def _on_updated(self, message: mcp_types.ResourceUpdatedNotification) -> None:
        # Append derived event with server attribution (no synthetic counters)
        uri_str = str(message.params.uri)
        server = await self._derive_server(uri_str)
        self._updates.append(ResourceUpdateEvent(server=server, uri=uri_str))
        # Append the typed notification for debugging/inspection
        self._raw.append(message)
        await self._run_hooks()

    async def _on_list_changed(self, message: mcp_types.ResourceListChangedNotification) -> None:
        # Attribute origin using compositor-captured child notifications when available
        names = list(self._compositor.pop_recent_list_changed())
        self._list_changed.update(names)
        # Record the typed notification
        self._raw.append(message)
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
        self._updates.append(ResourceUpdateEvent(server=name, uri=uri))
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
