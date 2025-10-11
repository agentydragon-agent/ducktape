from __future__ import annotations

from fastmcp.client import Client
from fastmcp.server import FastMCP
from hamcrest import assert_that, empty, has_item, has_properties
import pytest

from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.mcp.resources.clients import ResourcesClient
from adgn.mcp.resources.server import make_resources_server
from tests.util.notifications import enable_resources_caps


class _StubGatewaySession:
    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    async def subscribe_resource(self, uri):  # type: ignore[no-untyped-def]
        self.subscribed.append(str(uri))

    async def unsubscribe_resource(self, uri):  # type: ignore[no-untyped-def]
        self.unsubscribed.append(str(uri))


class _StubGatewayClient:
    def __init__(self) -> None:
        self.session = _StubGatewaySession()


def _make_origin() -> FastMCP:
    m = NotifyingFastMCP("origin")

    @m.resource(
        "resource://foo/bar",
        name="dummy",
        mime_type="text/plain",
        description="dummy",
    )
    async def foo_bar() -> str:
        return "ok"

    # Ensure this origin advertises resources.subscribe for gating
    enable_resources_caps(m, subscribe=True)
    return m


@pytest.mark.asyncio
async def test_subscriptions_index_updates_on_unmount():
    # Compositor with one origin server mounted
    comp = Compositor("comp")
    origin = _make_origin()
    await comp.mount_inproc("origin", origin)

    # Resources server with a stub gateway client that records sub/unsub calls
    gw = _StubGatewayClient()
    res_server = make_resources_server(name="resources", gateway_client=gw, compositor=comp)

    async with Client(res_server) as client:
        # Subscribe to an origin resource via the resources server tool
        rc = ResourcesClient(client)
        await rc.subscribe(server="origin", uri="resource://foo/bar")

        # Verify call reached the stub and index reflects the subscription
        assert gw.session.subscribed, "expected a subscribe call"
        # Use typed client helper to parse the subscriptions index
        idx = await rc.list_subscriptions()
        assert_that(
            idx.subscriptions,
            has_item(has_properties(server="origin", uri="resource://foo/bar")),
        )

        # Unmount the origin server; the resources server should not attempt remote
        # unsubscription. It should drop the non-pinned record from the index.
        await comp.unmount_server("origin")

        # Ensure no unsubscribe call happened as a result of unmount
        assert not gw.session.unsubscribed, "unexpected remote unsubscribe on unmount"

        # Subscriptions index should be empty now
        idx2 = await rc.list_subscriptions()
        assert_that(idx2.subscriptions, empty())
