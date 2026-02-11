from __future__ import annotations

from fastmcp.client import Client

from adgn.mcp._shared.urls import parse_any_url
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP


def _u(s: str) -> str:
    """Normalize a URI using the shared AnyUrl adapter for comparisons."""
    return str(parse_any_url(s))


async def test_queued_notifications_flush_on_first_list(make_buffered_client):
    # Create server and queue a list_changed before any sessions exist
    srv = NotifyingFastMCP("child")
    await srv.broadcast_resource_list_changed()  # queued (no sessions yet)

    async with make_buffered_client({"child": srv}) as (client, _comp, buf):
        # Trigger a server-side list (captures session and flushes pending)
        await client.session.list_resources()
        batch = buf.poll()
        # Expect child reported in list_changed (attributed by compositor)
        assert "child" in batch.resource_list_changed


async def test_broadcast_continues_after_session_failure(make_buffered_client):
    # Create server and open two client sessions
    srv = NotifyingFastMCP("notifier")
    async with make_buffered_client({"notifier": srv}) as (client1, comp, buf):
        # Open a second client attached to the same Compositor
        async with Client(comp) as client2:
            # Prime both sessions by listing resources once
            await client1.session.list_resources()
            await client2.session.list_resources()

        # After client2 context exits, simulate broadcast with one stale session
        target_uri = _u("notifier://test")
        await srv.broadcast_resource_updated(target_uri)

        batch = buf.poll()
        # Expect at least one resources_updated event delivered to the active client
        updated_uris = [uri for _server, uri in batch.iter_updated_uris()]
        assert target_uri in updated_uris, (
            "expected resources_updated for the active session despite one failing client"
        )
