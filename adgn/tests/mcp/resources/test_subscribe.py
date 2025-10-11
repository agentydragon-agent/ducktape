from fastmcp.client import Client
import pytest

from adgn.mcp.resources.clients import ResourcesClient
from adgn.mcp.resources.server import make_resources_server
from tests.util.notifications import enable_resources_caps


@pytest.mark.asyncio
async def test_client_resource_subscribe_and_unsubscribe(make_pg_compositor):
    """Subscribe/unsubscribe to a server resource via the Compositor client.

    Uses an origin that exposes a dummy resource and advertises subscribe capability.
    """

    from adgn.mcp.compositor.server import Compositor
    from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

    # Compositor with a simple origin that exposes the resource to subscribe to
    comp = Compositor("comp")
    origin = NotifyingFastMCP("origin")
    enable_resources_caps(origin, subscribe=True)

    # Register minimal subscribe/unsubscribe handlers on the origin
    ll = origin._mcp_server  # low-level server

    @ll.subscribe_resource()
    async def _sub(_uri):  # type: ignore[no-redef]
        return None

    @ll.unsubscribe_resource()
    async def _unsub(_uri):  # type: ignore[no-redef]
        return None

    @origin.resource("resource://foo/bar", name="dummy", mime_type="text/plain")
    async def _foo_bar() -> str:
        return "ok"

    await comp.mount_inproc("origin", origin)

    # Gateway client connected to the compositor front door
    async with Client(comp) as gw:
        # Resources server mounted standalone using the compositor gateway client
        async with Client(make_resources_server(gateway_client=gw, compositor=comp)) as res:
            rc = ResourcesClient(res)
            # Subscribe to the resource and then unsubscribe
            await rc.subscribe(server="origin", uri="resource://foo/bar")
            await rc.unsubscribe(server="origin", uri="resource://foo/bar")
