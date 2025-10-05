from __future__ import annotations

from types import SimpleNamespace

import pytest

from adgn.agent.loop_control import Abort, Continue, RequireAny
from adgn.agent.mcp_manager import McpManager
from adgn.agent.server.bus import ServerBus, UiEndTurn, UiMessage
from adgn.agent.server.mode_handler import ServerModeHandler
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.mcp.testing.typed_stubs import TypedClient
from adgn.mcp.ui.server import make_ui_mcp


@pytest.fixture
def bus():
    return ServerBus()


@pytest.mark.asyncio
async def test_ui_send_message_and_end_turn_bus(bus) -> None:
    server = make_ui_mcp("ui", bus)

    async with McpManager({}) as m:
        await m.attach_server("ui", make_inproc_slot_spec(server))
        sess = await m.get_session("ui")
        client = TypedClient.from_server(server, sess)

        # Send a markdown message
        send_models = client.models["send_message"]
        UiMsgIn = send_models.Input or UiMessage
        UiMsgOut = send_models.Output or UiMessage
        msg = UiMsgIn(mime="text/markdown", content="**hello**")
        out: UiMsgOut = await client.send_message(msg)
        assert out.mime == "text/markdown" and out.content == "**hello**"

        drained = bus.drain_messages()
        assert drained and isinstance(drained[0], UiMessage)
        assert drained[0].content == "**hello**"

        # Request end_turn
        end_models = client.models["end_turn"]
        EndIn = end_models.Input
        assert EndIn is not None
        await client.end_turn(EndIn())
        # bus flag is set and an UiEndTurn item was queued
        assert bus.end_turn_requested is True
        assert any(isinstance(x, UiEndTurn) for x in bus.drain_messages())


def test_ui_handler_abort_on_end_turn(bus) -> None:
    def dummy_poll():
        return SimpleNamespace(resources_updated=[])

    h = ServerModeHandler(bus=bus, poll_notifications=dummy_poll)

    # No end_turn pending -> RequireAny tool usage
    dec = h.on_before_sample()
    assert isinstance(dec, Continue)
    assert isinstance(dec.tool_policy, RequireAny)

    # Push end_turn -> handler should Abort
    bus.push_end_turn()
    dec2 = h.on_before_sample()
    assert isinstance(dec2, Abort)
