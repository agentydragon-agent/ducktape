from __future__ import annotations

import pytest


async def test_unmount_pinned_server_errors_and_kept(compositor, backend_server):
    srv = backend_server
    # Mount and then pin
    await compositor.mount_inproc("backend", srv, pinned=True)

    # Attempt to unmount should raise and keep the server
    with pytest.raises(RuntimeError):
        await compositor.unmount_server("backend")

    specs = await compositor.mount_specs()
    assert "backend" in specs, "pinned server should remain mounted after failed unmount"
