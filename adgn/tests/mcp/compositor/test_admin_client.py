from __future__ import annotations

from adgn.mcp.compositor.admin import CompositorAdminServer, DetachServerArgs


async def test_admin_server_detach(make_pg_compositor, make_simple_mcp):
    """Test CompositorAdminServer.detach_server() removes a mounted server."""
    async with make_pg_compositor({"backend": make_simple_mcp}) as comp:
        # Verify backend is mounted
        states = await comp.server_entries()
        assert "backend" in states

        # Create admin server and detach backend
        admin_server = CompositorAdminServer(compositor=comp)
        await admin_server.detach_server_tool.fn(DetachServerArgs(name="backend"))

        # Verify backend was removed
        states_after = await comp.server_entries()
        assert "backend" not in states_after
