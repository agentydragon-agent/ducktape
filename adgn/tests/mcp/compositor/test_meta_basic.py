from __future__ import annotations

from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp.snapshots import RunningServerEntry, ServerEntry
from tests.conftest import TEST_BACKEND_SERVER_NAME


async def test_compositor_meta_resources_available(make_compositor, make_simple_mcp):
    """Test compositor_meta server resources without policy gateway."""
    async with make_compositor({TEST_BACKEND_SERVER_NAME: make_simple_mcp}) as (client, comp):
        # Get meta server
        meta_server = comp.compositor_meta.server

        # Read per-mount state from the compositor_meta server
        # Expect running or initializing depending on initialization timing
        # Note: The URI gets prefixed with the mount name (compositor_meta)
        state_uri = comp.compositor_meta.add_resource_prefix(
            meta_server.server_state_resource.uri_template.format(server=TEST_BACKEND_SERVER_NAME)
        )
        entry: ServerEntry = await read_text_json_typed(client, state_uri, ServerEntry)
        assert isinstance(entry, RunningServerEntry)
