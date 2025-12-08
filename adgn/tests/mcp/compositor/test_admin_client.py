from __future__ import annotations

from adgn.mcp.compositor.clients import CompositorAdminClient, CompositorMetaClient


async def test_admin_client_list_and_detach(make_pg_compositor, make_simple_mcp):
    # make_pg_compositor auto-creates a PolicyEngine and mounts its reader
    async with make_pg_compositor({"backend": make_simple_mcp}) as (sess, _engine):
        admin = CompositorAdminClient(sess)
        meta = CompositorMetaClient(sess)
        states = await meta.list_states()
        assert "backend" in states
        # Detach via admin client (allowed for in-proc proxies)
        await admin.detach_server(name="backend")
        states_after = await meta.list_states()
        assert "backend" not in states_after
