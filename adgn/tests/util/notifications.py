from __future__ import annotations

import json
from typing import Iterable

from fastmcp.client.messages import MessageHandler
from mcp import types

from adgn.openai_utils.model import InputTextPart, UserMessage


class CaptureUpdates(MessageHandler):
    def __init__(self) -> None:
        self.updated: list[str] = []

    async def on_resource_updated(self, message: types.ResourceUpdatedNotification) -> None:  # type: ignore[override]
        self.updated.append(str(message.params.uri))


async def subscribe_head(session) -> None:
    """Subscribe to chat head updates for the connected server."""
    await session.subscribe_resource("chat://head")


def _iter_text_parts(message: UserMessage) -> Iterable[str]:
    for part in message.content or []:
        if isinstance(part, InputTextPart) and part.text:
            yield part.text


def parse_system_notification_payload(message: str | UserMessage) -> dict:
    """Extract and parse the JSON payload in a tagged system notification message.

    Expects the message to contain:
      <system notification>\n{json}\n</system notification>
    Returns the parsed dict, or raises ValueError on malformed input.
    """
    if isinstance(message, UserMessage):
        parts = list(_iter_text_parts(message))
        if not parts:
            raise ValueError("Message has no text parts to inspect")
        text = "\n".join(parts)
    else:
        text = message

    start_tag = "<system notification>"
    end_tag = "</system notification>"
    start = text.find(start_tag)
    end = text.find(end_tag)
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Not a tagged system notification message")
    payload_str = text[start + len(start_tag) : end].strip()
    return json.loads(payload_str)


def enable_resources_caps(
    server, *, subscribe: bool | None = None, list_changed: bool | None = None
) -> None:  # type: ignore[no-untyped-def]
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
    base_get_caps = ll.get_capabilities

    def patched_create_initialization_options(
        notification_options=None, experimental_capabilities=None, **kwargs
    ):  # type: ignore[no-untyped-def]
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

    def patched_get_capabilities(notification_options, experimental_capabilities):  # type: ignore[no-untyped-def]
        caps = base_get_caps(notification_options, experimental_capabilities)
        res_caps = caps.resources
        if subscribe is not None or list_changed is not None:
            if res_caps is None:
                res_caps = types.ResourcesCapability()
            if subscribe is not None:
                res_caps.subscribe = subscribe
            if list_changed is not None:
                res_caps.listChanged = list_changed
            caps.resources = res_caps
        return caps

    ll.get_capabilities = patched_get_capabilities

    if subscribe:
        # Ensure subscribe/unsubscribe handlers exist so requests succeed.
        if types.SubscribeRequest not in ll.request_handlers:

            @ll.subscribe_resource()
            async def _test_subscribe(_uri):
                return None

        if types.UnsubscribeRequest not in ll.request_handlers:

            @ll.unsubscribe_resource()
            async def _test_unsubscribe(_uri):
                return None


class SubscriptionRecorder:
    """Record subscribe/unsubscribe requests made to a server for test assertions."""

    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []


def install_subscription_recorder(server) -> SubscriptionRecorder:  # type: ignore[no-untyped-def]
    """Register lightweight subscribe/unsubscribe handlers that record URIs."""
    ll = getattr(server, "_mcp_server", None)
    if ll is None:
        raise RuntimeError("Server has no _mcp_server to patch")
    recorder = SubscriptionRecorder()

    @ll.subscribe_resource()
    async def _record_subscribe(uri):
        recorder.subscribed.append(str(uri))
        return None

    @ll.unsubscribe_resource()
    async def _record_unsubscribe(uri):
        recorder.unsubscribed.append(str(uri))
        return None

    return recorder
