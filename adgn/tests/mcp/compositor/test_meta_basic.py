from __future__ import annotations

from fastmcp.server.server import add_resource_prefix
import pytest

from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp.snapshots import RunningServerEntry, ServerEntry
from tests.conftest import TEST_BACKEND_SERVER_NAME


@pytest.mark.requires_docker
async def test_compositor_meta_resources_available(pg_client):
    # Get compositor and meta server
    comp = pg_client.transport.server
    meta_server = comp.compositor_meta.server

    # Read per-mount state from the compositor_meta server
    # Expect running or initializing depending on initialization timing
    # Note: The URI gets prefixed with the mount name (compositor_meta)
    state_uri = add_resource_prefix(
        meta_server.server_state_resource.uri_template.format(server=TEST_BACKEND_SERVER_NAME),
        comp.compositor_meta.prefix,
    )
    entry: ServerEntry = await read_text_json_typed(pg_client, state_uri, ServerEntry)
    assert isinstance(entry, RunningServerEntry)
