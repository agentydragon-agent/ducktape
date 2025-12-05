from __future__ import annotations

from adgn.mcp._shared.constants import (
    COMPOSITOR_META_SERVER_NAME,
    COMPOSITOR_META_SERVERS_URI,
    COMPOSITOR_META_STATE_URI_PATTERN,
)
from adgn.mcp.compositor.server import Compositor, MountEvent
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.mcp.snapshots import ServerEntry


def make_compositor_meta_server(*, compositor: Compositor, name: str = COMPOSITOR_META_SERVER_NAME) -> NotifyingFastMCP:
    """Expose Compositor mount metadata as resources on a dedicated server.

    This removes the need for synthetic mcp-server:// URIs and avoids special-casing
    in the resources aggregator.
    """
    m = NotifyingFastMCP(
        name=name,
        instructions=(
            "Compositor metadata. Resources under this server expose per-mount state, instructions and capabilities."
        ),
    )

    @m.resource(
        COMPOSITOR_META_SERVERS_URI,
        name="compositor.servers",
        mime_type="application/json",
        description="List of all mounted servers",
    )
    async def servers_list() -> list[str]:
        """Return list of all mounted server names for discovery."""
        entries = await compositor.server_entries()
        return list(entries.keys())

    @m.resource(
        COMPOSITOR_META_STATE_URI_PATTERN,
        name="compositor.state",
        mime_type="application/json",
        description="Per-server state snapshot (initializing|running|failed)",
    )
    async def server_state(server: str) -> ServerEntry:
        entries = await compositor.server_entries()
        if (entry := entries.get(server)) is None:
            raise KeyError(server)
        return entry

    # Instructions and capabilities are embedded in the per-server state (InitializeResult)
    # via server_state above; no separate resources are exposed to avoid duplication.

    # Register mount change listener to emit notifications without container coupling
    async def _on_mount_change(name: str, action: MountEvent) -> None:
        # Always signal list-changed when mounts change
        await m.broadcast_resource_list_changed()
        # For new state availability or mount, update the per-server state resource
        if action in (MountEvent.MOUNTED, MountEvent.STATE):
            await m.broadcast_resource_updated(COMPOSITOR_META_STATE_URI_PATTERN.format(server=name))

    compositor.add_mount_listener(_on_mount_change)

    return m
