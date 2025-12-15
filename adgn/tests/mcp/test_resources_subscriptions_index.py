from __future__ import annotations

from hamcrest import assert_that, empty, has_item, has_properties

from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.resources.server import ResourcesSubscribeArgs


async def test_subscriptions_index_updates_on_unmount(compositor, origin_with_recorder, typed_resources_client):
    # Compositor with one origin server mounted
    origin, hooks = origin_with_recorder
    origin_prefix = MCPMountPrefix("origin")
    await compositor.mount_inproc(origin_prefix, origin)

    # Subscribe to an origin resource via the resources server tool
    await typed_resources_client.subscribe(ResourcesSubscribeArgs(server=origin_prefix, uri="resource://foo/bar"))
    assert hooks.subscribed, "expected origin to receive subscribe"
    # Index reflects the subscription
    idx = await typed_resources_client.list_subscriptions()
    assert_that(idx.subscriptions, has_item(has_properties(server=origin_prefix, uri="resource://foo/bar")))

    # Unmount the origin server; subscription should be dropped from index
    await compositor.unmount_server(origin_prefix)
    assert not hooks.unsubscribed, "unexpected origin unsubscribe on unmount"
    idx2 = await typed_resources_client.list_subscriptions()
    assert_that(idx2.subscriptions, empty())
