from __future__ import annotations

from fastmcp.server import FastMCP
from hamcrest import assert_that, contains, contains_inanyorder, empty, has_item, has_properties

from adgn.mcp.resources.clients import ResourcesClient


async def test_list_changes_subscriptions_visible_and_cleared_on_unmount(compositor, resources_client):
    origin = FastMCP("origin")
    await compositor.mount_inproc("origin", origin)

    # Subscribe to list changes for the origin server
    rc = ResourcesClient(resources_client)
    await rc.subscribe_list_changes(server="origin")
    idx = await rc.list_subscriptions()
    assert_that(idx.list_subscriptions, has_item(has_properties(server="origin", present=True, active=True)))

    # Unmount origin; selection should be cleared from the index
    await compositor.unmount_server("origin")
    idx2 = await rc.list_subscriptions()
    assert_that(idx2.list_subscriptions, empty())


async def test_list_changes_multiple_subscriptions_and_unsubscribe(compositor, resources_client):
    a = FastMCP("a")
    b = FastMCP("b")
    await compositor.mount_inproc("a", a)
    await compositor.mount_inproc("b", b)

    rc = ResourcesClient(resources_client)
    # Subscribe to both origins
    await rc.subscribe_list_changes(server="a")
    await rc.subscribe_list_changes(server="b")
    idx = await rc.list_subscriptions()
    assert_that([x.server for x in idx.list_subscriptions], contains_inanyorder("a", "b"))

    # Unsubscribe one
    await rc.unsubscribe_list_changes(server="a")
    idx2 = await rc.list_subscriptions()
    assert_that([x.server for x in idx2.list_subscriptions], contains("b"))
