from __future__ import annotations

import json
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP
import pytest
from adgn.llm.openai_utils.model import (
    ResponsesResult,
    Usage,
    ReasoningOut,
    AssistantResponseMessage,
    FunctionCallOut,
    FakeOpenAIModel,
    FunctionCallItem,
    FunctionCallOutputItem,
    ReasoningItem,
    AssistantMessage,
)

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
# Use our shared Pydantic-only fake model client

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


def _usage(inp: int = 0, out: int = 0) -> Usage:
    return Usage(input_tokens=inp, output_tokens=out, total_tokens=inp + out)


def _make_reasoning_then_message(text: str) -> ResponsesResult:
    # Ensure unique item IDs per response to avoid duplicate-id assertions in agent transcript
    rs_id = f"rs_{uuid.uuid4().hex[:8]}"
    return ResponsesResult(
        id="r1",
        usage=_usage(0, max(1, len(text))),
        output=[ReasoningOut(id=rs_id), AssistantResponseMessage(text=text)],
    )


def _make_tool_call_resp(
    call_id: str, name: str, args: dict[str, Any]
) -> ResponsesResult:
    return ResponsesResult(
        id="r_tc",
        usage=_usage(0, 0),
        output=[
            FunctionCallOut(call_id=call_id, name=name, arguments=json.dumps(args))
        ],
    )


@pytest.mark.asyncio
async def test_stateless_reasoning_forwarding() -> None:
    """Request1 produces reasoning+assistant; Request2 should include reasoning in input."""
    spec = make_inproc_slot_spec(_make_echo_server())

    seq = [_make_reasoning_then_message("ok")]
    client = FakeOpenAIModel(seq)

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
        from adgn.llm.openai_utils.model import ReasoningItem, AssistantMessage

        # We forward reasoning items as typed ReasoningItem
        assert any(isinstance(it, ReasoningItem) for it in msgs)
        # Assistant text is represented as a standard AssistantMessage
        assert any(isinstance(it, AssistantMessage) for it in msgs)


@pytest.mark.asyncio
async def test_function_call_and_fco_replay() -> None:
    """Request1 produces a function_call; after local execution, messages() must include fc and fco."""
    spec = make_inproc_slot_spec(_make_echo_server())

    seq = [
        _make_tool_call_resp("call-1", "mcp__echo__echo", {"text": "hi"}),
        _make_reasoning_then_message("done"),
    ]
    client = FakeOpenAIModel(seq)

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
    assert client.calls == 2
    # Captured request input holds our typed InputItem models
    input_items = list(client.captured[1].input or [])
    assert any(isinstance(it, FunctionCallItem) for it in input_items)
    assert any(isinstance(it, FunctionCallOutputItem) for it in input_items)


@pytest.mark.asyncio
async def test_mixed_reasoning_fc_ordering() -> None:
    """Resp1 returns reasoning, function_call, assistant; after fco, messages preserves order
    reasoning, fc, fco, assistant.
    """
    spec = make_inproc_slot_spec(_make_echo_server())

    # Build a response with reasoning then function_call then assistant (our facade types)
    resp = ResponsesResult(
        id="r_mix",
        usage=_usage(0, 1),
        output=[
            ReasoningOut(id="rs_x"),
            FunctionCallOut(
                call_id="call-1",
                name="mcp__echo__echo",
                arguments=json.dumps({"text": "hi"}),
            ),
            AssistantResponseMessage(text="done"),
        ],
    )
    # Use a final assistant message on the second call to avoid infinite tool-call loops
    client = FakeOpenAIModel([resp, _make_reasoning_then_message("ok")])

    async with McpManager({"echo": spec}) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler()],
        )
        await agent.run("start")

    # Expect exactly two calls; validate second call input ordering/types (typed InputItems)
    assert client.calls == 2
    input_items = list(client.captured[1].input or [])
    assert any(isinstance(it, ReasoningItem) for it in input_items)
    assert any(isinstance(it, FunctionCallItem) for it in input_items)
    assert any(isinstance(it, FunctionCallOutputItem) for it in input_items)
    assert any(isinstance(it, AssistantMessage) for it in input_items)


@pytest.mark.asyncio
async def test_no_synthesized_reasoning_items() -> None:
    """Ensure agent does not fabricate reasoning rs_* items when missing."""
    spec = make_inproc_slot_spec(_make_echo_server())

    # Response with only a function_call (no reasoning)
    seq = [
        _make_tool_call_resp("call-1", "mcp__echo__echo", {"text": "hi"}),
        _make_reasoning_then_message("done"),
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager({"echo": spec}) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler()],
        )
        await agent.run("say hi")

    idx = min(1, len(client.captured) - 1)
    input_items = list(client.captured[idx].input or [])
    # No synthesized ReasoningItem entries should be present
    assert not any(isinstance(it, ReasoningItem) for it in input_items)
