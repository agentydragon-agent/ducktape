from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec

# OpenAI Responses SDK types
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openai.types.responses.response_reasoning_item import (
    ResponseReasoningItem,
    Summary as ReasoningSummary,
)
from openai.types.responses.response_usage import (
    ResponseUsage,
    InputTokensDetails,
    OutputTokensDetails,
)


def _usage(inp: int = 0, out: int = 0) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=inp,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens=out,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=inp + out,
    )


def _make_reasoning_then_tool(*, call_id: str, name: str, arguments: dict[str, Any]) -> Response:
    return Response(
        id="resp_1",
        created_at=0,
        model="dummy-model",
        object="response",
        output=[
            ResponseReasoningItem(
                id="rs_1",
                type="reasoning",
                summary=[ReasoningSummary(type="summary_text", text="thinking...")],
            ),
            ResponseFunctionToolCall(
                type="function_call",
                call_id=call_id,
                name=name,
                arguments=json.dumps(arguments),
            ),
        ],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=_usage(0, 0),
    )


def _make_final_assistant(text: str) -> Response:
    msg = ResponseOutputMessage(
        id="m1",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )
    return Response(
        id="resp_2",
        created_at=1,
        model="dummy-model",
        object="response",
        output=[msg],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=_usage(0, max(1, len(text))),
    )


class _CapturingResponses:
    def __init__(self, seq: list[Response]) -> None:
        self._seq = seq
        self.calls = 0
        self.captured: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Response:  # OpenAI AsyncResponses-compatible
        self.captured.append(dict(kwargs))
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        return self._seq[idx]


class CapturingClient:
    def __init__(self, seq: list[Response]) -> None:
        self.responses = _CapturingResponses(seq)


def _make_echo_server() -> FastMCP:
    mcp = FastMCP("echo")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:
        return {"ok": True, "echo": text}

    return mcp


@pytest.mark.asyncio
async def test_reasoning_threading_filters_reasoning_from_next_input() -> None:
    spec = make_inproc_slot_spec(_make_echo_server())

    # Sequence: model reasons then calls a tool, then returns a final message
    seq = [
        _make_reasoning_then_tool(call_id="call-1", name="mcp__echo__echo", arguments={"text": "hi"}),
        _make_final_assistant("ok"),
    ]
    client = CapturingClient(seq)

    async with McpManager({"echo": spec}) as mcp:
        from adgn_llm.mini_codex.aggregating_handler import AutoHandler

        agent = await MiniCodex.create(
            model="dummy-model",
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[AutoHandler()],
        )

        res = await agent.run("say hi")

    # Assertions: the second Responses.create should NOT include any reasoning items in input
    assert res.text.strip() == "ok"
    assert client.responses.calls == 2
    # Capture the input sent on the second call
    second = client.responses.captured[1]
    input_items = second.get("input") or []
    assert isinstance(input_items, list)
    assert all((not isinstance(it, dict)) or (it.get("type") != "reasoning") for it in input_items), (
        f"Reasoning item leaked into next-turn input: {json.dumps(input_items, ensure_ascii=False)}"
    )
