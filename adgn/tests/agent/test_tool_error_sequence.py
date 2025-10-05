from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.loggers import RecordingHandler
from adgn.agent.loop_control import Auto, Continue
from adgn.agent.mcp_manager import McpManager
from adgn.agent.reducer import BaseHandler
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.openai_utils.model import FakeOpenAIModel
from tests.agent.ws_helpers import assert_function_call_output_structured


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
    async with McpManager({}) as mcp:
        await mcp.attach_server("editor", spec)
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
    assert_function_call_output_structured(rec.records, ok=False, error="boom")
