from __future__ import annotations

from fastmcp.client import Client
from pydantic import BaseModel, ConfigDict

from adgn.mcp._shared.client_helpers import call_simple_ok
from adgn.mcp._shared.resources import read_text_json_typed
from adgn.mcp._shared.uris import subscriptions_index_uri


class SubscriptionSummary(BaseModel):
    server: str
    uri: str
    pinned: bool
    present: bool
    active: bool
    last_error: str | None = None
    model_config = ConfigDict(extra="forbid")


class ListSubscriptionSummary(BaseModel):
    server: str
    present: bool
    active: bool
    model_config = ConfigDict(extra="forbid")


class SubscriptionsIndex(BaseModel):
    subscriptions: list[SubscriptionSummary]
    list_subscriptions: list[ListSubscriptionSummary] = []
    model_config = ConfigDict(extra="forbid")


class ResourcesClient:
    """Typed client helpers for the `resources` server.

    Expects a Client connected to the Compositor front door.
    """

    def __init__(self, client: Client) -> None:
        # Public attribute for simplicity/inspection in tests
        self.client: Client = client

    async def list_subscriptions(self) -> SubscriptionsIndex:
        """Read the subscriptions index resource and parse into a typed model."""
        uri = subscriptions_index_uri()
        return await read_text_json_typed(self.client.session, uri, SubscriptionsIndex)

    # ---- Tools (typed wrappers) ---------------------------------------------

    async def subscribe(self, *, server: str, uri: str) -> None:
        """Subscribe to updates for a resource via the resources server."""
        await call_simple_ok(
            self.client, name="subscribe", arguments={"server": server, "uri": uri}
        )

    async def unsubscribe(self, *, server: str, uri: str) -> None:
        """Unsubscribe from updates for a resource via the resources server."""
        await call_simple_ok(
            self.client, name="unsubscribe", arguments={"server": server, "uri": uri}
        )

    async def subscribe_list_changes(self, *, server: str) -> None:
        await call_simple_ok(
            self.client, name="subscribe_list_changes", arguments={"server": server}
        )

    async def unsubscribe_list_changes(self, *, server: str) -> None:
        await call_simple_ok(
            self.client, name="unsubscribe_list_changes", arguments={"server": server}
        )
