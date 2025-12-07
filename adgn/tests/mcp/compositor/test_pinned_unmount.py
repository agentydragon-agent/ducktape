from __future__ import annotations

import pytest


async def test_unmount_pinned_server_errors_and_kept(compositor, backend_server):
    # Mount and then pin
    await compositor.mount_inproc("backend", backend_server, pinned=True)

    # Attempt to unmount should raise and keep the server
    with pytest.raises(RuntimeError, match="Cannot unmount pinned server"):
        await compositor.unmount_server("backend")

    # Verify server is still mounted by checking server entries
    entries = await compositor.server_entries()
    assert "backend" in entries, "pinned server should remain mounted after failed unmount"
