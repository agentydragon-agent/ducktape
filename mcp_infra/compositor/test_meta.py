from __future__ import annotations

import pytest_bazel

from mcp_infra.resource_utils import read_text_json_typed
from mcp_infra.snapshots import RunningServerEntry, ServerEntry

_BACKEND = "backend"


async def test_compositor_meta_resources_available(make_compositor, make_simple_mcp):
    """Test compositor_meta per-mount state resource is readable."""
    async with make_compositor({_BACKEND: make_simple_mcp}) as (client, comp):
        meta_server = comp.compositor_meta.server

        state_uri = comp.compositor_meta.add_resource_prefix(
            meta_server.server_state_resource.uri_template.format(server=_BACKEND)
        )
        entry: ServerEntry = await read_text_json_typed(client, state_uri, ServerEntry)
        assert isinstance(entry, RunningServerEntry)


async def test_meta_discovery_lists_mounted_servers(make_compositor, make_simple_mcp):
    """Test compositor_meta discovery resource lists mounted servers."""
    async with make_compositor({_BACKEND: make_simple_mcp}) as (sess, comp):
        meta_server = comp.compositor_meta.server
        discovery_uri = comp.compositor_meta.add_resource_prefix(meta_server.servers_list_resource.uri)

        servers: list[str] = await read_text_json_typed(sess, discovery_uri, list[str])

        assert isinstance(servers, list)
        assert _BACKEND in servers


async def test_meta_presents_inproc_mount_state(make_compositor, make_simple_mcp):
    """Test compositor_meta per-server state for in-process mounts."""
    async with make_compositor({_BACKEND: make_simple_mcp}) as (sess, comp):
        meta_server = comp.compositor_meta.server
        backend_state_uri = comp.compositor_meta.add_resource_prefix(
            meta_server.server_state_resource.uri_template.format(server=_BACKEND)
        )

        entry: ServerEntry = await read_text_json_typed(sess, backend_state_uri, ServerEntry)

        assert isinstance(entry, RunningServerEntry)
        assert entry.initialize is not None
        assert isinstance(entry.tools, list)


if __name__ == "__main__":
    pytest_bazel.main()
