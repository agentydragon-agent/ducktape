from __future__ import annotations

import pytest

from adgn.mcp.compositor.server import Compositor


async def test_unmount_pinned_server_errors_and_kept(backend_server):
    comp = Compositor("comp")
    # Mount and then pin
    await comp.mount_inproc("backend", backend_server, pinned=True)

    # Attempt to unmount should raise and keep the server
    with pytest.raises(RuntimeError):
        await comp.unmount_server("backend")

    specs = await comp.mount_specs()
    assert "backend" in specs, "pinned server should remain mounted after failed unmount"
