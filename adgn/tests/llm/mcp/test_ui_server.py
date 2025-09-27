from __future__ import annotations

import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mcp.testing.typed_stubs import TypedClient
from adgn.llm.mcp.ui.server import make_ui_mcp
from adgn.llm.mini_codex.ui.shared_bus import UiBus, UiMessage, UiEndTurn
from adgn.llm.mini_codex.ui.ui_handler import UiAutoHandler
from adgn.llm.mini_codex.loop_control import Abort, Continue, RequireAny


@pytest.fixture
def bus():
    return UiBus()


@pytest.mark.asyncio
async def test_ui_send_message_and_end_turn_bus(bus) -> None:
    server = make_ui_mcp("ui", bus)

    async with McpManager({"ui": make_inproc_slot_spec(server)}) as m:
        sess = await m.get_session("ui")
        client = TypedClient.from_server(server, sess)

        # Send a markdown message
        UiMsgIn = client.models["send_message"].Input or UiMessage  # type: ignore[attr-defined]
        UiMsgOut = client.models["send_message"].Output or UiMessage  # type: ignore[attr-defined]
        msg = UiMsgIn(mime="text/markdown", content="**hello**")
        out: UiMsgOut = await client.send_message(msg)  # type: ignore[attr-defined]
        assert out.mime == "text/markdown" and out.content == "**hello**"

        drained = bus.drain_messages()
        assert drained and isinstance(drained[0], UiMessage)
        assert drained[0].content == "**hello**"

        # Request end_turn
        EndIn = client.models["end_turn"].Input  # type: ignore[attr-defined]
        await client.end_turn(EndIn())  # type: ignore[attr-defined]
        # bus flag is set and an UiEndTurn item was queued
        assert bus.end_turn_requested is True
        assert any(isinstance(x, UiEndTurn) for x in bus.drain_messages())


def test_ui_handler_abort_on_end_turn(bus) -> None:
    h = UiAutoHandler(bus=bus)

    # No end_turn pending -> RequireAny tool usage
    dec = h.on_before_sample()
    assert isinstance(dec, Continue)
    assert isinstance(dec.tool_policy, RequireAny)

    # Push end_turn -> handler should Abort
    bus.push_end_turn()
    dec2 = h.on_before_sample()
    assert isinstance(dec2, Abort)
