from __future__ import annotations

from fastmcp.client import Client
from fastmcp.server.server import add_resource_prefix

from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp.snapshots import RunningServerEntry, ServerEntry
from tests.conftest import TEST_BACKEND_SERVER_NAME


async def test_meta_presents_inproc_mounts(make_pg_compositor, make_simple_mcp):
    # make_pg_compositor auto-creates a PolicyEngine and mounts its reader
    async with make_pg_compositor({TEST_BACKEND_SERVER_NAME: make_simple_mcp}) as comp:
        # Get meta server from compositor
        meta_server = comp.compositor_meta.server

        async with Client(comp) as sess:
            # First, check that the discovery resource exists and lists mounted servers
            # Note: The URI gets prefixed with the mount name (compositor_meta)
            discovery_uri = add_resource_prefix(meta_server.servers_list_resource.uri, comp.compositor_meta.prefix)

            # Read the discovery resource using the typed helper
            servers: list[str] = await read_text_json_typed(sess, discovery_uri, list[str])

            # Should list at least the backend server we mounted
            assert isinstance(servers, list)
            assert TEST_BACKEND_SERVER_NAME in servers

            # Now read an individual server's state using the template pattern
            # Note: The URI gets prefixed with the mount name (compositor_meta)
            backend_state_uri = add_resource_prefix(
                meta_server.server_state_resource.uri_template.format(server=TEST_BACKEND_SERVER_NAME),
                comp.compositor_meta.prefix,
            )

            # Read state using the typed helper
            entry: ServerEntry = await read_text_json_typed(sess, backend_state_uri, ServerEntry)

            # In-proc mounts should be running when read via compositor_meta
            assert isinstance(entry, RunningServerEntry)
            assert entry.initialize is not None
            assert isinstance(entry.tools, list)
