from fastmcp.client import Client

from adgn.mcp.resources.clients import ResourcesClient
from tests.util.notifications import enable_resources_caps, install_subscription_recorder


async def test_client_resource_subscribe_and_unsubscribe(compositor, resources_client):
    """Subscribe/unsubscribe to a server resource via the Compositor client.

    Uses an origin that exposes a dummy resource and advertises subscribe capability.
    """

    from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

    # Compositor with a simple origin that exposes the resource to subscribe to
    origin = NotifyingFastMCP("origin")
    recorder = install_subscription_recorder(origin)
    enable_resources_caps(origin, subscribe=True)

    @origin.resource("resource://foo/bar", name="dummy", mime_type="text/plain")
    async def _foo_bar() -> str:
        return "ok"

    await compositor.mount_inproc("origin", origin)

    # Gateway client connected to the compositor front door
    async with Client(compositor) as gw:
        rc = ResourcesClient(resources_client)
        # Subscribe to the resource and then unsubscribe
        await rc.subscribe(server="origin", uri="resource://foo/bar")
        await rc.unsubscribe(server="origin", uri="resource://foo/bar")
        assert recorder.subscribed, "expected origin to receive subscribe"
        assert recorder.unsubscribed, "expected origin unsubscribe call"
