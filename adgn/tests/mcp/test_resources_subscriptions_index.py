from __future__ import annotations

from hamcrest import assert_that, empty, has_item, has_properties

from adgn.mcp.resources.clients import ResourcesClient


async def test_subscriptions_index_updates_on_unmount(compositor, origin_with_recorder, resources_client):
    # Compositor with one origin server mounted
    origin, hooks = origin_with_recorder
    await compositor.mount_inproc("origin", origin)

    # Subscribe to an origin resource via the resources server tool
    rc = ResourcesClient(resources_client)
    await rc.subscribe(server="origin", uri="resource://foo/bar")
    assert hooks.subscribed, "expected origin to receive subscribe"
    # Index reflects the subscription
    idx = await rc.list_subscriptions()
    assert_that(idx.subscriptions, has_item(has_properties(server="origin", uri="resource://foo/bar")))

    # Unmount the origin server; subscription should be dropped from index
    await compositor.unmount_server("origin")
    assert not hooks.unsubscribed, "unexpected origin unsubscribe on unmount"
    idx2 = await rc.list_subscriptions()
    assert_that(idx2.subscriptions, empty())
