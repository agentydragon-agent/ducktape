from __future__ import annotations

from typing import Any
import pytest

from adgn.openai_utils.model import (
    AssistantMessage,
    FakeOpenAIModel,
    FunctionCallItem,
    FunctionCallOutputItem,
    ReasoningItem,
    ResponsesResult,
)
from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import AutoHandler
from adgn.agent.mcp_manager import McpManager
from tests.fixtures.responses import ResponsesFactory
# Use our shared Pydantic-only fake model client

# Examples and references:
# - Demo scripts: :/adgn/examples/openai_api/stateless_two_step_demo.py (text & tools stateless 2-step continuation)
# - OpenAI Responses API reference: https://platform.openai.com/docs/api-reference/responses
# - OpenAI Cookbook examples (reasoning & function-call orchestration):
#   - reasoning_items.ipynb: https://github.com/openai/openai-cookbook/blob/main/examples/responses_api/reasoning_items.ipynb
#   - reasoning_function_calls.ipynb: https://github.com/openai/openai-cookbook/blob/main/examples/reasoning_function_calls.ipynb


_rf = ResponsesFactory("gpt-5-nano")


def _make_reasoning_then_message(text: str):
    # Ensure unique item IDs per response to avoid duplicate-id assertions in agent transcript
    return _rf.make(
        _rf.make_item_reasoning(),
        _rf.assistant_text(text),
    )


def _make_tool_call_resp(
    name: str, args: dict[str, Any], *, call_id: str | None = None
) -> ResponsesResult:
    return _rf.make_tool_call(name, args, call_id)


@pytest.mark.asyncio
async def test_stateless_reasoning_forwarding(make_echo_spec) -> None:
    """Request1 produces reasoning+assistant; Request2 should include reasoning in input."""
    specs = make_echo_spec()

    seq = [_make_reasoning_then_message("ok")]
    client = FakeOpenAIModel(seq)

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler()],
        )

        await agent.run("say hi")

        # Reasoning should be present in the agent transcript/messages for stateless forwarding
        msgs = agent.messages

        # We forward reasoning items as typed ReasoningItem
        assert any(isinstance(it, ReasoningItem) for it in msgs)
        # Assistant text is represented as a standard AssistantMessage
        assert any(isinstance(it, AssistantMessage) for it in msgs)


@pytest.mark.asyncio
async def test_function_call_and_fco_replay(make_echo_spec) -> None:
    """Request1 produces a function_call; after local execution, messages() must include fc and fco."""
    specs = make_echo_spec()

    seq = [
        _make_tool_call_resp("mcp__echo__echo", {"text": "hi"}),
        _make_reasoning_then_message("done"),
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,
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
async def test_mixed_reasoning_fc_ordering(make_echo_spec) -> None:
    """Resp1 returns reasoning, function_call, assistant; after fco, messages preserves order
    reasoning, fc, fco, assistant.
    """
    specs = make_echo_spec()

    # Build a response with reasoning then function_call then assistant (our facade types)
    resp = _rf.make(
        _rf.make_item_reasoning(),
        _rf.tool_call("mcp__echo__echo", {"text": "hi"}),
        _rf.assistant_text("done"),
    )
    # Use a final assistant message on the second call to avoid infinite tool-call loops
    client = FakeOpenAIModel([resp, _make_reasoning_then_message("ok")])

    async with McpManager(specs) as mcp:
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
async def test_no_synthesized_reasoning_items(make_echo_spec) -> None:
    """Ensure agent does not fabricate reasoning rs_* items when missing."""
    specs = make_echo_spec()

    # Response with only a function_call (no reasoning)
    seq = [
        _make_tool_call_resp("mcp__echo__echo", {"text": "hi"}),
        _make_reasoning_then_message("done"),
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager(specs) as mcp:
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


@pytest.mark.asyncio
async def test_model_provided_tool_output_records_without_execution(
    responses_factory: ResponsesFactory,
    make_echo_spec,
) -> None:
    """If the model supplies tool output inline, agent should not run the tool again."""

    specs = make_echo_spec()
    seq = [
        responses_factory.make_tool_call_with_output(
            "mcp__echo__echo",
            {"text": "hi"},
            {"ok": True, "echo": "hi"},
        )
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler()],
        )

        await agent.run("say hi")

    msgs = agent.messages
    assert any(isinstance(it, FunctionCallOutputItem) for it in msgs)
    assert not agent.pending_function_calls
    assert client.calls == 1
