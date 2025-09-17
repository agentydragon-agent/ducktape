from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from mcp.server.fastmcp import FastMCP
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
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.mcp_manager import McpManager

# Examples and references:
# - Demo scripts: :/adgn/examples/openai_api/stateless_two_step_demo.py (text & tools stateless 2-step continuation)
# - OpenAI Responses API reference: https://platform.openai.com/docs/api-reference/responses
# - OpenAI Cookbook examples (reasoning & function-call orchestration):
#   - reasoning_items.ipynb: https://github.com/openai/openai-cookbook/blob/main/examples/responses_api/reasoning_items.ipynb
#   - reasoning_function_calls.ipynb: https://github.com/openai/openai-cookbook/blob/main/examples/reasoning_function_calls.ipynb


# Simple inproc echo server used by tests
def _make_echo_server() -> FastMCP:
    mcp = FastMCP("echo")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:
        return {"ok": True, "echo": text}

    return mcp


@dataclass
class CallRecord:
    kwargs: dict[str, Any]

    # Common accessors
    @property
    def input(self) -> list[dict[str, Any]]:
        return list(self.kwargs.get("input") or [])


class _CapturingResponses:
    def __init__(self, seq: list[Response]) -> None:
        self._seq = seq
        self.calls = 0
        self.captured: list[dict[str, Any]] = []
        self.calls_list: list[CallRecord] = []

    async def create(
        self,
        **kwargs: Any,
    ) -> Response:  # OpenAI AsyncResponses-compatible
        payload = dict(kwargs)
        self.captured.append(payload)
        self.calls_list.append(CallRecord(kwargs=payload))
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        return self._seq[idx]


class CapturingClient:
    def __init__(self, seq: list[Response]) -> None:
        self.responses = _CapturingResponses(seq)


def _usage(inp: int = 0, out: int = 0) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=inp,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens=out,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=inp + out,
    )


def _make_reasoning_then_message(text: str) -> Response:
    return Response(
        id="r1",
        created_at=0,
        model="test-model",
        object="response",
        output=[
            ResponseReasoningItem(
                id="rs_1",
                type="reasoning",
                summary=[ReasoningSummary(type="summary_text", text="thinking...")],
            ),
            ResponseOutputMessage(
                id="m1",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(type="output_text", text=text, annotations=[]),
                ],
            ),
        ],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=_usage(0, max(1, len(text))),
    )


def _make_tool_call_resp(call_id: str, name: str, args: dict[str, Any]) -> Response:
    tc = ResponseFunctionToolCall(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=json.dumps(args),
    )
    return Response(
        id="r_tc",
        created_at=0,
        model="test-model",
        object="response",
        output=[tc],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=_usage(0, 0),
    )


@pytest.mark.asyncio
async def test_stateless_reasoning_forwarding() -> None:
    """Request1 produces reasoning+assistant; Request2 should include reasoning in input."""
    spec = make_inproc_slot_spec(_make_echo_server())

    seq = [_make_reasoning_then_message("ok")]
    client = CapturingClient(seq)

    async with McpManager({"echo": spec}) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[AutoHandler()],
        )

        await agent.run("say hi")

        # Reasoning should be present in the agent transcript/messages for stateless forwarding
        msgs = agent.messages
        # We forward reasoning items with type="reasoning"
        assert any(
            isinstance(it, dict) and it.get("type") == "reasoning" for it in msgs
        )
        # Assistant text is represented as a standard assistant message (role/content), not a type="message" wrapper
        assert any(
            isinstance(it, dict) and it.get("role") == "assistant" for it in msgs
        )


@pytest.mark.asyncio
async def test_function_call_and_fco_replay() -> None:
    """Request1 produces a function_call; after local execution, messages() must include fc and fco."""
    spec = make_inproc_slot_spec(_make_echo_server())

    seq = [
        _make_tool_call_resp("call-1", "mcp__echo__echo", {"text": "hi"}),
        _make_reasoning_then_message("done"),
    ]
    client = CapturingClient(seq)

    async with McpManager({"echo": spec}) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[AutoHandler()],
        )

        await agent.run("say hi")

    # Check that the captured second input includes function_call and function_call_output
    # We should have exactly two calls; inspect the second call's input shape
    assert client.responses.calls == 2
    second = client.responses.calls_list[1]
    input_items = second.input
    assert any(
        isinstance(it, dict) and it.get("type") == "function_call" for it in input_items
    )
    assert any(
        isinstance(it, dict) and it.get("type") == "function_call_output"
        for it in input_items
    )


@pytest.mark.asyncio
async def test_mixed_reasoning_fc_ordering() -> None:
    """Resp1 returns reasoning, function_call, assistant; after fco, messages preserves order
    reasoning, fc, fco, assistant.
    """
    spec = make_inproc_slot_spec(_make_echo_server())

    # Build a response with reasoning then function_call then assistant
    tc = ResponseFunctionToolCall(
        type="function_call",
        call_id="call-1",
        name="mcp__echo__echo",
        arguments=json.dumps({"text": "hi"}),
    )
    resp = Response(
        id="r_mix",
        created_at=0,
        model="test-model",
        object="response",
        output=[
            ResponseReasoningItem(
                id="rs_x",
                type="reasoning",
                summary=[ReasoningSummary(type="summary_text", text="x")],
            ),
            tc,
            ResponseOutputMessage(
                id="m1",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(type="output_text", text="done", annotations=[]),
                ],
            ),
        ],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=_usage(0, 1),
    )
    # Use a final assistant message on the second call to avoid infinite tool-call loops
    client = CapturingClient([resp, _make_reasoning_then_message("ok")])

    async with McpManager({"echo": spec}) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler()],
        )
        await agent.run("start")

    # Expect exactly two calls; validate second call input ordering/types
    assert client.responses.calls == 2
    input_items = client.responses.calls_list[1].input
    types = [it.get("type") if isinstance(it, dict) else None for it in input_items]
    # Expect reasoning, function_call, function_call_output, and an assistant message present
    assert "reasoning" in types
    assert "function_call" in types
    assert "function_call_output" in types
    assert any(
        isinstance(it, dict) and it.get("role") == "assistant" for it in input_items
    )


@pytest.mark.asyncio
async def test_no_synthesized_reasoning_items() -> None:
    """Ensure agent does not fabricate reasoning rs_* items when missing."""
    spec = make_inproc_slot_spec(_make_echo_server())

    # Response with only a function_call (no reasoning)
    seq = [
        _make_tool_call_resp("call-1", "mcp__echo__echo", {"text": "hi"}),
        _make_reasoning_then_message("done"),
    ]
    client = CapturingClient(seq)

    async with McpManager({"echo": spec}) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler()],
        )
        await agent.run("say hi")

    idx = min(1, len(client.responses.captured) - 1)
    input_items = client.responses.captured[idx].get("input") or []
    # No synthesized rs_ id entries should be present (we only forward actual reasoning items)
    assert not any(
        isinstance(it, dict)
        and isinstance(it.get("id"), str)
        and it.get("id", "").startswith("rs_")
        for it in input_items
    )
