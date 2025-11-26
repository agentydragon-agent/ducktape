from __future__ import annotations

from fastmcp.server import FastMCP
import pytest


def _backend(name: str = "backend") -> FastMCP:
    m = FastMCP(name)

    @m.tool(name="ping")
    def ping() -> str:
        return "pong"

    return m


async def test_unmount_pinned_server_errors_and_kept(compositor):
    srv = _backend()
    # Mount and then pin
    await compositor.mount_inproc("backend", srv, pinned=True)

    # Attempt to unmount should raise and keep the server
    with pytest.raises(RuntimeError):
        await compositor.unmount_server("backend")

    specs = await compositor.mount_specs()
    assert "backend" in specs, "pinned server should remain mounted after failed unmount"
