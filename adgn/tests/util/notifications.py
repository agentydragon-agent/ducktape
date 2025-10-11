from __future__ import annotations

import json
from fastmcp.client.messages import MessageHandler
from mcp import types as mcp_types


class CaptureUpdates(MessageHandler):
    def __init__(self) -> None:
        self.updated: list[str] = []

    async def on_resource_updated(self, message: mcp_types.ResourceUpdatedNotification) -> None:  # type: ignore[override]
        self.updated.append(str(message.params.uri))


async def subscribe_head(session) -> None:
    """Subscribe to chat head updates for the connected server."""
    await session.subscribe_resource("chat://head")


def parse_system_notification_payload(text: str) -> dict:
    """Extract and parse the JSON payload in a tagged system notification message.

    Expects the message to contain:
      <system notification>\n{json}\n</system notification>
    Returns the parsed dict, or raises ValueError on malformed input.
    """
    start_tag = "<system notification>"
    end_tag = "</system notification>"
    start = text.find(start_tag)
    end = text.find(end_tag)
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Not a tagged system notification message")
    payload_str = text[start + len(start_tag) : end].strip()
    return json.loads(payload_str)


def enable_resources_caps(server, *, subscribe: bool | None = None, list_changed: bool | None = None) -> None:  # type: ignore[no-untyped-def]
    """Monkeypatch a FastMCP/NotifyingFastMCP server to advertise resources capabilities.

    This wraps the server's low-level create_initialization_options() to inject
    experimental_capabilities for the 'resources' group.
    Call this before mounting/connecting the server so the init handshake carries
    the desired caps.
    """
    ll = getattr(server, "_mcp_server", None)
    if ll is None:
        raise RuntimeError("Server has no _mcp_server to patch")
    base_create = ll.create_initialization_options

    def patched_create_initialization_options(notification_options=None, experimental_capabilities=None, **kwargs):  # type: ignore[no-untyped-def]
        caps = dict(experimental_capabilities or {})
        res = dict(caps.get("resources") or {})
        if subscribe is not None:
            res["subscribe"] = subscribe
        if list_changed is not None:
            res["listChanged"] = list_changed
        if res:
            caps["resources"] = res
        return base_create(
            notification_options=notification_options,
            experimental_capabilities=caps,
            **kwargs,
        )

    ll.create_initialization_options = patched_create_initialization_options
