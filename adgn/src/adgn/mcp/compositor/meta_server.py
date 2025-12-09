from __future__ import annotations

from adgn.mcp._shared.constants import (
    COMPOSITOR_META_SERVER_NAME,
    COMPOSITOR_META_SERVERS_URI,
    COMPOSITOR_META_STATE_URI_PATTERN,
)
from adgn.mcp.compositor.server import Compositor, MountEvent
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.snapshots import ServerEntry


def make_compositor_meta_server(*, compositor: Compositor, name: str = COMPOSITOR_META_SERVER_NAME) -> EnhancedFastMCP:
    """Expose Compositor mount metadata as resources on a dedicated server.

    This removes the need for synthetic mcp-server:// URIs and avoids special-casing
    in the resources aggregator.
    """
    m = EnhancedFastMCP(
        name=name,
        instructions=(
            "Compositor metadata server exposing state and configuration of all mounted MCP servers.\n\n"
            "**What it provides:**\n"
            "- List of all mounted servers (resource: resource://compositor_meta/servers)\n"
            "- Per-server state snapshots (initializing, running, or failed)\n"
            "- Server capabilities (tools, resources, prompts, logging support)\n"
            "- Server-provided instructions for how to use their tools/resources\n\n"
            "**Use this to:**\n"
            "- Discover what servers are available and their current state\n"
            "- Read server-specific instructions before using their tools\n"
            "- Check capabilities to understand what features each server supports\n"
            "- Monitor server health (detect failed mounts, view error messages)\n\n"
            "Resources follow the pattern `resource://compositor_meta/state/{server}` for per-server state."
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
