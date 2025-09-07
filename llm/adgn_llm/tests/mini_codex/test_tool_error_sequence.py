from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import (
    McpManager,
    ServerSlot,
)
from adgn_llm.mcp.inproc import open_fastmcp_client_session
from mcp.server.fastmcp import FastMCP


def _make_failing_server() -> FastMCP:
    mcp = FastMCP("editor")

    @mcp.tool()
    def fail(x: int) -> dict[str, Any]:  # noqa: ARG001 - required by schema
        return {"ok": False, "error": "boom"}

    return mcp


class DummyClient(BaseModel):
    pass  # placeholder so MiniCodex type checks; we will not invoke real API


@pytest.mark.asyncio
async def test_tool_error_is_surfaced_in_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    # Build in-proc failing server slot using FastMCP in-memory client
    async def open_fn(stack):
        return await stack.enter_async_context(open_fastmcp_client_session(_make_failing_server))

    slot = ServerSlot(name="editor", open_fn=open_fn)
    mcp = McpManager({"editor": slot})

    # Stub OpenAI responses to return one tool call first, then no further calls (break loop)
    from openai.types.responses import ResponseFunctionToolCall

    call_once_state = {"n": 0}

    class _RespOneCall:
        def __init__(self):
            self.output = [
                ResponseFunctionToolCall(
                    type="function_call",  # required by pydantic
                    call_id="call1",
                    name="mcp__editor__fail",
                    arguments=json.dumps({"x": 1}),
                )
            ]

    class _RespNoCall:
        def __init__(self):
            self.output = []

    import adgn_llm.mini_codex.agent as agent_mod

    def _fake_create(client, **kwargs):
        if call_once_state["n"] == 0:
            call_once_state["n"] = 1
            return _RespOneCall()
        return _RespNoCall()

    monkeypatch.setattr(agent_mod, "_responses_create_with_retry", _fake_create)

    # Create agent and run one turn
    agent = await MiniCodex.create(
        model="dummy-model",
        mcp=mcp,
        system="You are a code agent.",
        client=None,  # not used due to stubbed responses
    )
    try:
        result = await agent.run("call failing tool once")
    finally:
        await agent.close()

    # Extract the function_call_output from the sequence and assert failure payload surfaced
    fco_items = [evt for evt in result.sequence if evt.get("kind") == "function_call_output"]
    assert fco_items, "No function_call_output captured"
    payload = json.loads(fco_items[-1]["output"])  # output is JSON-serialized string

    assert payload.get("ok") is False
    assert payload.get("error") == "boom"
