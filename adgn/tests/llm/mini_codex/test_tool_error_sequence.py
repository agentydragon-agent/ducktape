from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
import pytest
from adgn.llm.openai_utils.model import (
    FakeOpenAIModel,
    ResponsesResult,
    Usage,
    FunctionCallOut,
    AssistantResponseMessage,
)

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import BaseHandler
from adgn.llm.mini_codex.loggers import RecordingHandler
from adgn.llm.mini_codex.loop_control import Auto, Continue
from adgn.llm.mini_codex.mcp_manager import McpManager


def _make_failing_server() -> FastMCP:
    mcp = FastMCP("editor")

    @mcp.tool()
    def fail(x: int) -> dict[str, Any]:
        return {"ok": False, "error": "boom"}

    return mcp


@pytest.mark.asyncio
async def test_tool_error_is_surfaced_in_sequence(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
) -> None:
    # Build in-proc failing server spec using FastMCP
    spec = make_inproc_slot_spec(_make_failing_server())
    async with McpManager({"editor": spec}) as mcp:
        # Create agent and run one turn

        class _AutoHandler(BaseHandler):
            def on_before_sample(self):  # type: ignore[override]
                return Continue(Auto())

        rec = RecordingHandler()

        client = FakeOpenAIModel(
            [
                ResponsesResult(
                    id="fc",
                    usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0),
                    output=[
                        FunctionCallOut(
                            call_id="call_1",
                            name="mcp__editor__fail",
                            arguments=json.dumps({"x": 1}),
                        )
                    ],
                ),
                ResponsesResult(
                    id="msg",
                    usage=Usage(input_tokens=0, output_tokens=1, total_tokens=1),
                    output=[AssistantResponseMessage(text="done")],
                ),
            ]
        )
        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="You are a code agent.",
            client=client,
            handlers=[_AutoHandler(), rec],
        )
        await agent.run("call failing tool once")

    # Extract the function_call_output from the recording handler and assert failure payload surfaced
    fco_items = [
        evt for evt in rec.records if evt.get("kind") == "function_call_output"
    ]
    assert fco_items, "No function_call_output captured"
    payload = json.loads(fco_items[-1]["output"])  # output is JSON-serialized string

    assert payload.get("ok") is False
    assert payload.get("error") == "boom"
