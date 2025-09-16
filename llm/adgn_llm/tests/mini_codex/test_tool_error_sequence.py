from __future__ import annotations

import json
from typing import Any

import pytest
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.aggregating_handler import BaseHandler
from adgn_llm.mini_codex.loggers import RecordingHandler
from adgn_llm.mini_codex.loop_control import Auto, Continue
from adgn_llm.mini_codex.mcp_manager import McpManager
from mcp.server.fastmcp import FastMCP
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)


def _make_failing_server() -> FastMCP:
    mcp = FastMCP("editor")

    @mcp.tool()
    def fail(x: int) -> dict[str, Any]:  # noqa: ARG001 - required by schema
        return {"ok": False, "error": "boom"}

    return mcp


class FakeResponses:
    def __init__(self, model: str) -> None:
        self.model = model
        self.calls = 0

    async def create(self, **kwargs: Any) -> Response:  # type: ignore[override]
        self.calls += 1
        # First call: request to invoke the failing tool once
        if self.calls == 1:
            tc = ResponseFunctionToolCall(
                type="function_call",
                call_id="call1",
                name="mcp__editor__fail",
                arguments=json.dumps({"x": 1}),
            )
            return Response(
                id="r1",
                created_at=0,
                model=self.model,
                object="response",
                output=[tc],
                parallel_tool_calls=False,
                tool_choice="auto",
                tools=[],
                usage=ResponseUsage(
                    input_tokens=0,
                    input_tokens_details=InputTokensDetails(cached_tokens=0),
                    output_tokens=0,
                    output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                    total_tokens=0,
                ),
            )
        # Second call: no further tool calls (break loop)
        msg = ResponseOutputMessage(
            id="m1",
            type="message",
            role="assistant",
            status="completed",
            content=[ResponseOutputText(type="output_text", text="done", annotations=[])],
        )
        return Response(
            id="r2",
            created_at=1,
            model=self.model,
            object="response",
            output=[msg],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
            usage=ResponseUsage(
                input_tokens=0,
                input_tokens_details=InputTokensDetails(cached_tokens=0),
                output_tokens=1,
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                total_tokens=1,
            ),
        )


class FakeOpenAIClient:
    def __init__(self, model: str) -> None:
        self.responses = FakeResponses(model)


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

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="You are a code agent.",
            client=FakeOpenAIClient(responses_factory.model),  # type: ignore[arg-type]
            handlers=[_AutoHandler(), rec],
        )
        await agent.run("call failing tool once")

    # Extract the function_call_output from the recording handler and assert failure payload surfaced
    fco_items = [evt for evt in rec.records if evt.get("kind") == "function_call_output"]
    assert fco_items, "No function_call_output captured"
    payload = json.loads(fco_items[-1]["output"])  # output is JSON-serialized string

    assert payload.get("ok") is False
    assert payload.get("error") == "boom"
