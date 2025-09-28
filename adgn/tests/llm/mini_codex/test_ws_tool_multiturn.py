from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError

from fastapi.testclient import TestClient
from mcp import types as mcp_types
import pytest

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mini_codex.ui import protocol
from adgn.llm.mini_codex.ui.server import create_app
from adgn.llm.mini_codex.ui.shared_bus import UiBus
from adgn.llm.mini_codex.ui.ui_handler import UiAutoHandler
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mcp.ui.server import make_ui_mcp
from tests.llm.support.openai_mock import make_mock

Envelope = protocol.Envelope


class DummyClient:
    @property
    def responses(self):  # pragma: no cover
        raise AssertionError(
            "responses.create should not be called directly in this test"
        )


@pytest.mark.timeout(5)
def test_ws_tool_multiturn(
    responses_factory,
    make_echo_spec,
) -> None:
    """WS multi-turn: user -> echo tool -> typed MCP result -> UI message."""

    state = {"step": 0}

    async def responses_create(_req):
        step = state["step"]
        state["step"] += 1
        if step == 0:
            return responses_factory.make_tool_call(
                "mcp__echo__echo", {"text": "hello"}, call_id="call_echo"
            )
        if step == 1:
            return responses_factory.make_tool_call(
                "mcp__ui__send_message",
                {"mime": "text/markdown", "content": "**hello**"},
                call_id="call_ui_msg",
            )
        return responses_factory.make_tool_call(
            "mcp__ui__end_turn", {}, call_id="call_ui_end"
        )

    client = make_mock(responses_create)
    bus = UiBus()

    specs = make_echo_spec()
    specs["ui"] = make_inproc_slot_spec(make_ui_mcp("ui", bus))

    # Create a separate async function to handle both creation and test execution
    async def _run_test():
        async with McpManager(specs) as mcp_mgr:
            agent = await MiniCodex.create(
                model="test-model",
                mcp=mcp_mgr,
                system="You are a test agent.",
                client=client,
                handlers=[UiAutoHandler(bus=bus)],
                parallel_tool_calls=False,
            )
            return agent

    agent = asyncio.run(_run_test())

    app = create_app(require_static_assets=False)
    app.state.ui_bus = bus
    app.state.session.attach_agent(agent)

    try:
        with TestClient(app) as client_ws, client_ws.websocket_connect("/ws") as ws:
            ws.send_json({"type": "send", "text": "use echo"})

            for _ in range(20):
                env = Envelope.model_validate(ws.receive_json())
                if env.payload.type == "accepted":
                    break
            else:  # pragma: no cover - defensive
                raise AssertionError("accepted not received")

            saw_echo_output = False
            saw_ui_message = False
            saw_ui_end = False
            saw_finished = False

            for _ in range(100):
                payload = Envelope.model_validate(ws.receive_json()).payload
                if payload.type == "approval_pending":
                    ws.send_json({"type": "approve", "call_id": payload.call_id})
                    continue

                if payload.type == "function_call_output":
                    result = mcp_types.CallToolResult.model_validate(payload.result)
                    if payload.call_id == "call_echo":
                        structured = result.structuredContent or {}
                        assert structured == {"ok": True, "echo": "hello"}
                        saw_echo_output = True
                    elif payload.call_id == "call_ui_msg":
                        structured = result.structuredContent or {}
                        assert structured == {
                            "mime": "text/markdown",
                            "content": "**hello**",
                        }
                    elif payload.call_id == "call_ui_end":
                        structured = result.structuredContent or {}
                        assert structured == {"kind": "EndTurn"}
                        saw_ui_end = True
                    continue

                if payload.type == "ui_message":
                    assert payload.message.mime == "text/markdown"
                    assert payload.message.content == "**hello**"
                    saw_ui_message = True
                    continue

                if (
                    payload.type == "run_status"
                    and payload.run_state.status == "finished"
                ):
                    saw_finished = True
                    break

            assert saw_echo_output, "echo tool output not emitted"
            assert saw_ui_message, "UiMessageEvt not emitted"
            assert saw_ui_end, "ui end_turn result not emitted"
            assert saw_finished, "run_status finished not emitted"
    except CancelledError:
        pass
