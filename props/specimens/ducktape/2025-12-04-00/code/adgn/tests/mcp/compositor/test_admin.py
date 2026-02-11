from __future__ import annotations

import pytest

from adgn.mcp._shared.constants import COMPOSITOR_META_SERVER_NAME


async def test_compositor_admin_attach_detach(admin_client, compositor, stdio_echo_spec):
    # Create a stdio child spec and attach
    await admin_client.attach_server(name="backend", spec=stdio_echo_spec)
    specs = await compositor.mount_specs()
    assert "backend" in specs

    # Detach should remove the server
    await admin_client.detach_server(name="backend")
    specs_after = await compositor.mount_specs()
    assert "backend" not in specs_after


async def test_compositor_admin_attach_twice_errors(admin_client, stdio_echo_spec):
    await admin_client.attach_server(name="backend2", spec=stdio_echo_spec)
    with pytest.raises(Exception, match=r"backend2.*already.*attached|name.*already.*exists"):
        await admin_client.attach_server(name="backend2", spec=stdio_echo_spec)


async def test_compositor_admin_detach_pinned_server_fails(admin_client):
    # Attempt to detach a pinned server should raise
    with pytest.raises(Exception, match=r"pinned|cannot.*detach"):
        await admin_client.detach_server(name=COMPOSITOR_META_SERVER_NAME)


async def test_compositor_admin_attach_invalid_name_errors(admin_client, stdio_echo_spec):
    # Invalid name containing double underscore should fail
    with pytest.raises(Exception, match=r"invalid.*name|double.*underscore"):
        await admin_client.attach_server(name="bad__name", spec=stdio_echo_spec)
