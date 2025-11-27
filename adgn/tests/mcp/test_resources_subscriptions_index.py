from __future__ import annotations

from hamcrest import assert_that, empty, has_item, has_properties


async def test_subscriptions_index_updates_on_unmount(compositor, origin_with_recorder, typed_resources_client):
    # Compositor with one origin server mounted
    origin, hooks = origin_with_recorder
    await compositor.mount_inproc("origin", origin)

    # Subscribe to an origin resource via the resources server tool
    await typed_resources_client.subscribe(server="origin", uri="resource://foo/bar")
    assert hooks.subscribed, "expected origin to receive subscribe"
    # Index reflects the subscription
    idx = await typed_resources_client.list_subscriptions()
    assert_that(idx.subscriptions, has_item(has_properties(server="origin", uri="resource://foo/bar")))

    # Unmount the origin server; subscription should be dropped from index
    await compositor.unmount_server("origin")
    assert not hooks.unsubscribed, "unexpected origin unsubscribe on unmount"
    idx2 = await typed_resources_client.list_subscriptions()
    assert_that(idx2.subscriptions, empty())
