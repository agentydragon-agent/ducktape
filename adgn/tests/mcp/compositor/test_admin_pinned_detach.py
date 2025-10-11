from __future__ import annotations

from fastmcp.exceptions import ToolError
import pytest

from adgn.mcp._shared.constants import COMPOSITOR_META_SERVER_NAME
from adgn.mcp.compositor.clients import CompositorAdminClient


@pytest.mark.asyncio
async def test_admin_cannot_detach_pinned_server(
    make_pg_compositor, approval_policy_reader_allow_all
):
    # make_pg_compositor mounts compositor_meta and compositor_admin pinned by default
    async with make_pg_compositor({"approval_policy": approval_policy_reader_allow_all}) as (
        sess,
        _comp,
    ):
        admin = CompositorAdminClient(sess)

        # Ensure compositor_meta is visible among mounts (via meta state resources)
        mounts_before = await admin.list_mounts()
        assert COMPOSITOR_META_SERVER_NAME in mounts_before

        # Attempt to detach the pinned meta server via the admin tool should error
        with pytest.raises(ToolError):
            await admin.detach_server(name=COMPOSITOR_META_SERVER_NAME)

        # Still present after failed detach
        mounts_after = await admin.list_mounts()
        assert COMPOSITOR_META_SERVER_NAME in mounts_after

