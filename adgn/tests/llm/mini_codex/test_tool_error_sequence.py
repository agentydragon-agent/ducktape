from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
import pytest
from adgn.llm.openai_utils.model import FakeOpenAIModel

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
                responses_factory.make_tool_call("mcp__editor__fail", {"x": 1}),
                responses_factory.make_assistant_message("done"),
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
    payload = fco_items[-1].get("result", {}) or {}
    structured = payload.get("structuredContent") or {}

    assert structured == {"ok": False, "error": "boom"}
