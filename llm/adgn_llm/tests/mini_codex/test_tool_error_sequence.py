from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mcp.inproc_utils import make_inproc_slot_spec
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
    # Build in-proc failing server spec using FastMCP
    spec = make_inproc_slot_spec(_make_failing_server())
    mcp = McpManager({"editor": spec})

    # Stub OpenAI responses to return one tool call first, then no further calls (break loop)
    from openai.types.responses import ResponseFunctionToolCall

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

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return _RespOneCall()
            return _RespNoCall()

    fake_client = type("_FakeClient", (), {"responses": FakeResponses()})()

    # Create agent and run one turn
    agent = await MiniCodex.create(
        model="dummy-model",
        mcp=mcp,
        system="You are a code agent.",
        client=fake_client,
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
