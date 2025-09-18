from __future__ import annotations

import asyncio
from concurrent.futures import CancelledError
import json

from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.mini_codex.ui import protocol
from adgn.llm.mini_codex.ui.server import create_app
from tests.llm.support.openai_builders import (
    make_assistant_text_response,
    make_function_call_response,
)
from tests.llm.support.openai_mock import make_mock

Envelope = protocol.Envelope


# Minimal in-proc MCP server with a single echo tool
mcp = FastMCP("echo")


@mcp.tool()
def echo(text: str) -> dict:
    return {"ok": True, "echo": text}


class DummyClient:
    @property
    def responses(self):  # pragma: no cover
        raise AssertionError(
            "responses.create should not be called directly in this test"
        )


@pytest.mark.timeout(5)
def test_ws_tool_multiturn(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS multi-turn: user -> function_call -> MCP result -> assistant text."""

    # Two-step mock via shared OpenAI mock: 1) function_call; 2) assistant message
    state = {"step": 0}

    async def responses_create(req):
        if state["step"] == 0:
            state["step"] += 1
            return make_function_call_response(
                tool_name="mcp__echo__echo",
                arguments_json=json.dumps({"text": "hello"}),
            )
        return make_assistant_text_response(text="done")

    client = make_mock(responses_create)

    spec = make_inproc_slot_spec(mcp)

    async def _mk_agent() -> tuple[MiniCodex, McpManager]:
        mcp_mgr = McpManager({"echo": spec})
        await mcp_mgr.__aenter__()
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp_mgr,
            system="You are a test agent.",
            client=client,
            handlers=[AutoHandler()],
            parallel_tool_calls=False,
        )
        return agent, mcp_mgr

    agent, _mcp_mgr = asyncio.run(_mk_agent())
    app = create_app()
    app.state.session.attach_agent(agent)

    try:
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            # 1) user sends message
            ws.send_json({"type": "send", "text": "use echo"})

            # Drain until accepted, but buffer any earlier events to process
            pre_msgs = []
            for _ in range(20):
                env = Envelope.model_validate(ws.receive_json())
                if env.payload.type == "accepted":
                    break
                pre_msgs.append(env)
            else:
                raise AssertionError("accepted not received")

            saw_tool_pending = False
            call_id = None
            saw_function_output = False
            saw_assistant_text = False
            saw_finished = False

            def process(env):
                nonlocal \
                    saw_tool_pending, \
                    call_id, \
                    saw_function_output, \
                    saw_assistant_text, \
                    saw_finished
                p = env.payload
                if p.type == "approval_pending":
                    saw_tool_pending = True
                    call_id = p.call_id
                    # approve
                    ws.send_json({"type": "approve", "call_id": call_id})
                elif p.type == "function_call_output":
                    body = json.loads(p.output)
                    assert body.get("ok") is True
                    assert body.get("echo") == "hello"
                    saw_function_output = True
                elif p.type == "assistant_text":
                    assert p.text == "done"
                    saw_assistant_text = True
                elif (
                    p.type == "run_status"
                    and getattr(p, "run_state", None)
                    and p.run_state.status == "finished"
                ):
                    saw_finished = True

            # process any buffered pre-accepted messages
            for env in pre_msgs:
                process(env)

            # 2) Expect approval_pending for tool call, then approve
            # 3) Expect function_call_output (MCP answer)
            # 4) Expect assistant_text and run_status finished
            for _ in range(50):
                env = Envelope.model_validate(ws.receive_json())
                process(env)
                if saw_finished:
                    break

            assert saw_tool_pending, "approval_pending not received"
            assert saw_function_output, "function_call_output not received"
            assert saw_assistant_text, "assistant_text not received"
            assert saw_finished, "run_status finished not received"
    except CancelledError:
        pass
