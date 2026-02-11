from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from tests.util.notifications import enable_resources_caps, install_subscription_recorder


async def test_client_resource_subscribe_and_unsubscribe(compositor, typed_resources_client):
    """Subscribe/unsubscribe to a server resource via the Compositor client.

    Uses an origin that exposes a dummy resource and advertises subscribe capability.
    """
    # Compositor with a simple origin that exposes the resource to subscribe to
    origin = NotifyingFastMCP("origin")
    recorder = install_subscription_recorder(origin)
    enable_resources_caps(origin, subscribe=True)

    @origin.resource("resource://foo/bar", name="dummy", mime_type="text/plain")
    async def _foo_bar() -> str:
        return "ok"

    await compositor.mount_inproc("origin", origin)

    # Subscribe to the resource and then unsubscribe
    await typed_resources_client.subscribe(server="origin", uri="resource://foo/bar")
    await typed_resources_client.unsubscribe(server="origin", uri="resource://foo/bar")
    assert recorder.subscribed, "expected origin to receive subscribe"
    assert recorder.unsubscribed, "expected origin unsubscribe call"
