from __future__ import annotations

import pytest

from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp._shared.uris import compositor_meta_state_uri
from adgn.mcp.snapshots import RunningServerEntry, ServerEntry


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_compositor_meta_resources_available(
    make_pg_compositor, approval_policy_reader_allow_all, backend_server
):
    async with make_pg_compositor({"backend": backend_server, "approval_policy": approval_policy_reader_allow_all}) as (
        sess,
        _comp,
    ):
        # Read per-mount state from the compositor_meta server
        # Expect running or initializing depending on initialization timing
        entry = await read_text_json_typed(sess.session, compositor_meta_state_uri("backend"), ServerEntry)
        assert isinstance(entry, RunningServerEntry)
