from __future__ import annotations

from typing import Final

from adgn.mcp.compositor.server import Compositor, MountEvent
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.snapshots import ServerEntry

# Resource URIs for compositor meta server
SERVERS_URI: Final[str] = "compositor://servers"
STATE_URI_PATTERN: Final[str] = "compositor://{server}/state"
# Note: INSTRUCTIONS and CAPABILITIES patterns are defined but not currently used
INSTRUCTIONS_URI_PATTERN: Final[str] = "compositor://{server}/instructions"
CAPABILITIES_URI_PATTERN: Final[str] = "compositor://{server}/capabilities"


class CompositorMetaServer(EnhancedFastMCP):
    """Compositor metadata server with typed resource access.

    Exposes mount metadata as resources on a dedicated server.
    This removes the need for synthetic mcp-server:// URIs and avoids special-casing
    in the resources aggregator.
    """

    def __init__(self, *, compositor: Compositor):
        """Create compositor metadata server.

        Args:
            compositor: Compositor instance to expose metadata for
        """
        super().__init__(
            name="Compositor Meta Server",
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

        self._compositor = compositor

        # Register resources
        @self.resource(
            SERVERS_URI,
            name="compositor.servers",
            mime_type="application/json",
            description="List of all mounted servers",
        )
        async def servers_list() -> list[str]:
            """Return list of all mounted server names for discovery."""
            entries = await self._compositor.server_entries()
            return list(entries.keys())

        @self.resource(
            STATE_URI_PATTERN,
            name="compositor.state",
            mime_type="application/json",
            description="Per-server state snapshot (initializing|running|failed)",
        )
        async def server_state(server: str) -> ServerEntry:
            entries = await self._compositor.server_entries()
            if (entry := entries.get(server)) is None:
                raise KeyError(server)
            return entry

        # Instructions and capabilities are embedded in the per-server state (InitializeResult)
        # via server_state above; no separate resources are exposed to avoid duplication.

        # Register mount change listener to emit notifications without container coupling
        async def _on_mount_change(name: str, action: MountEvent) -> None:
            # Always signal list-changed when mounts change
            await self.broadcast_resource_list_changed()
            # For new state availability or mount, update the per-server state resource
            if action in (MountEvent.MOUNTED, MountEvent.STATE):
                await self.broadcast_resource_updated(STATE_URI_PATTERN.format(server=name))

        self._compositor.add_mount_listener(_on_mount_change)


def make_compositor_meta_server(*, compositor: Compositor, name: str | None = None) -> CompositorMetaServer:
    """Factory function for backward compatibility.

    Args:
        compositor: Compositor instance to expose metadata for
        name: Unused (kept for API compatibility)

    Returns:
        CompositorMetaServer instance
    """
    return CompositorMetaServer(compositor=compositor)
