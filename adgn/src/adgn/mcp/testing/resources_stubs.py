"""Typed stubs for resources MCP server."""

from adgn.mcp._shared.constants import RESOURCES_SUBSCRIPTIONS_INDEX_URI
from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.resources.server import ListSubscribeArgs, ResourcesReadArgs
from adgn.mcp.resources.types import SubscriptionsIndex
from adgn.mcp.stubs.server_stubs import ServerStub


class ResourcesServerStub(ServerStub):
    """Typed stub for resources server operations."""

    async def subscribe(self, input: ResourcesReadArgs) -> SimpleOk:
        raise NotImplementedError  # Auto-wired at runtime

    async def unsubscribe(self, input: ResourcesReadArgs) -> SimpleOk:
        raise NotImplementedError  # Auto-wired at runtime

    async def subscribe_list_changes(self, input: ListSubscribeArgs) -> SimpleOk:
        raise NotImplementedError  # Auto-wired at runtime

    async def unsubscribe_list_changes(self, input: ListSubscribeArgs) -> SimpleOk:
        raise NotImplementedError  # Auto-wired at runtime

    async def list_subscriptions(self) -> SubscriptionsIndex:
        """Read the subscriptions index resource and parse into a typed model."""
        return await read_text_json_typed(
            self._client._session.session, RESOURCES_SUBSCRIPTIONS_INDEX_URI, SubscriptionsIndex
        )
