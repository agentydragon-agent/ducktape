from __future__ import annotations

from adgn.mcp._shared.constants import COMPOSITOR_ADMIN_SERVER_NAME
from adgn.mcp.compositor.admin import CompositorAdminServer
from adgn.mcp.compositor.clients import CompositorAdminClient, CompositorMetaClient


async def test_admin_client_list_and_detach(make_pg_compositor, make_simple_mcp):
    # make_pg_compositor auto-creates a PolicyEngine and mounts its reader
    async with make_pg_compositor({"backend": make_simple_mcp}) as (sess, _engine):
        # Get the compositor from the session transport
        from fastmcp.client.transports import FastMCPTransport

        assert isinstance(sess.transport, FastMCPTransport)
        comp = sess.transport.server
        from adgn.mcp.compositor.server import Compositor

        assert isinstance(comp, Compositor)

        # Mount admin server explicitly for this test
        admin_server = CompositorAdminServer(compositor=comp)
        await comp.mount_inproc(COMPOSITOR_ADMIN_SERVER_NAME, admin_server, pinned=True)

        admin = CompositorAdminClient(sess)
        meta = CompositorMetaClient(sess)
        states = await meta.list_states()
        assert "backend" in states
        # Detach via admin client (allowed for in-proc proxies)
        await admin.detach_server(name="backend")
        states_after = await meta.list_states()
        assert "backend" not in states_after
