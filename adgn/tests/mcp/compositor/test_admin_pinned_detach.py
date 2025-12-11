from __future__ import annotations

from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
import pytest

from adgn.mcp._shared.constants import COMPOSITOR_META_MOUNT_PREFIX
from adgn.mcp.compositor.admin import CompositorAdminServer, DetachServerArgs
from adgn.mcp.compositor.server import Compositor


async def test_admin_cannot_detach_pinned_server(make_pg_client, approval_policy_reader_stub):
    """Test CompositorAdminServer.detach_server() prevents detaching pinned servers."""
    async with make_pg_client({"approval_policy": approval_policy_reader_stub}) as sess:
        # Get compositor from session transport
        assert isinstance(sess.transport, FastMCPTransport)
        comp = sess.transport.server
        assert isinstance(comp, Compositor)

        # Verify compositor_meta is mounted (it's pinned by default)
        states_before = await comp.server_entries()
        assert COMPOSITOR_META_MOUNT_PREFIX in states_before

        # Create admin server and attempt to detach the pinned meta server
        admin_server = CompositorAdminServer(compositor=comp)
        with pytest.raises(ToolError, match="pinned"):
            await admin_server.detach_server_tool.fn(DetachServerArgs(name=COMPOSITOR_META_MOUNT_PREFIX))

        # Verify meta server still present after failed detach
        states_after = await comp.server_entries()
        assert COMPOSITOR_META_MOUNT_PREFIX in states_after
