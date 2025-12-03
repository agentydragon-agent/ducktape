from __future__ import annotations

import pytest

from adgn.agent.notifications.handler import format_notifications_message
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from tests.util.notifications import parse_system_notification_payload


@pytest.fixture
def make_notifier():
    """Factory for NotifyingFastMCP servers with emit tool."""

    def _make():
        m = NotifyingFastMCP("child")

        @m.tool(name="emit")
        async def emit():
            await m.broadcast_resource_list_changed()
            await m.broadcast_resource_updated("resource://dummy")
            return True

        return m

    return _make


@pytest.fixture
def notifier(make_notifier):
    """NotifyingFastMCP server for testing notification envelopes."""
    return make_notifier()


async def test_notifications_envelope_with_real_mcp(make_buffered_client, notifier):
    async with make_buffered_client({"child": notifier}) as (sess, _comp, buf):
        await sess.call_tool(name=build_mcp_function("child", "emit"), arguments={})
        batch = buf.poll()
        msg = format_notifications_message(batch)
        assert msg is not None
        payload = parse_system_notification_payload(msg)
        resources = payload.get("resources")
        assert isinstance(resources, dict)
        assert "child" in resources
        child_obj = resources["child"]
        assert isinstance(child_obj, dict)
        assert child_obj.get("list_changed") is True


async def test_notifications_envelope_after_remount(make_buffered_client, notifier, make_notifier):
    async with make_buffered_client({"child": notifier}) as (sess, comp, buf):
        await sess.call_tool(name=build_mcp_function("child", "emit"), arguments={})
        _ = buf.poll()

        # Unmount and re-mount a fresh notifier to simulate reconnect/new client path
        await comp.unmount_server("child")
        await comp.mount_inproc("child", make_notifier())

        await sess.call_tool(name=build_mcp_function("child", "emit"), arguments={})
        batch = buf.poll()
        msg = format_notifications_message(batch)
        assert msg is not None
        payload = parse_system_notification_payload(msg)
        resources = payload.get("resources")
        assert isinstance(resources, dict)
        assert "child" in resources
        assert resources["child"].get("list_changed") is True
