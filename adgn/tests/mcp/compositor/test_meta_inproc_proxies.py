from __future__ import annotations

from fastmcp.server.server import add_resource_prefix

from adgn.mcp._shared.constants import (
    COMPOSITOR_META_SERVER_NAME,
    COMPOSITOR_META_SERVERS_URI,
    COMPOSITOR_META_STATE_URI_PATTERN,
)
from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp.snapshots import RunningServerEntry, ServerEntry


async def test_meta_presents_inproc_mounts(make_pg_compositor, make_simple_mcp):
    # make_pg_compositor auto-creates a PolicyEngine and mounts its reader
    async with make_pg_compositor({"backend": make_simple_mcp}) as (sess, _engine):
        # First, check that the discovery resource exists and lists mounted servers
        # Note: The URI gets prefixed with the mount name (compositor_meta)
        discovery_uri = add_resource_prefix(COMPOSITOR_META_SERVERS_URI, COMPOSITOR_META_SERVER_NAME)

        # Read the discovery resource using the typed helper
        servers: list[str] = await read_text_json_typed(sess.session, discovery_uri, list[str])

        # Should list at least the backend server we mounted
        assert isinstance(servers, list)
        assert "backend" in servers

        # Now read an individual server's state using the template pattern
        # Note: The URI gets prefixed with the mount name (compositor_meta)
        backend_state_uri = add_resource_prefix(
            COMPOSITOR_META_STATE_URI_PATTERN.format(server="backend"), COMPOSITOR_META_SERVER_NAME
        )

        # Read state using the typed helper
        entry: ServerEntry = await read_text_json_typed(sess.session, backend_state_uri, ServerEntry)

        # In-proc mounts should be running when read via compositor_meta
        assert isinstance(entry, RunningServerEntry)
        assert entry.initialize is not None
        assert isinstance(entry.tools, list)
