from __future__ import annotations

from typing import Any

import pytest

from adgn.mcp.testing.simple_servers import EchoInput
from adgn.openai_utils.model import (
    AssistantMessage,
    FunctionCallItem,
    FunctionCallOutputItem,
    ReasoningItem,
    ResponsesResult,
)
from tests.agent.ui.typed_asserts import assert_items_exclude_instance, assert_items_include_instances
from tests.support.responses import ResponsesFactory


@pytest.fixture
def approval_policy_reader_allow_all(approval_policy_reader_stub):
    """Override global approval_policy_reader_allow_all with Docker-free stub.

    The global fixture (tests/conftest.py) uses PolicyEngine with Docker
    for realistic policy evaluation. This module tests message forwarding logic
    that doesn't need real policy execution, so we substitute the stub to:
    - Avoid Docker dependency for faster, more portable tests
    - Focus on message threading behavior, not policy evaluation
    """
    return approval_policy_reader_stub


def _make_reasoning_then_message(text: str, rf: ResponsesFactory) -> ResponsesResult:
    # Ensure unique item IDs per response to avoid duplicate-id assertions in agent transcript
    result: ResponsesResult = rf.make(rf.make_item_reasoning(), rf.assistant_text(text))
    return result


def _make_tool_call_resp(
    name: str, args: dict[str, Any], rf: ResponsesFactory, *, call_id: str | None = None
) -> ResponsesResult:
    result: ResponsesResult = rf.make_tool_call(name, args, call_id)
    return result


async def test_stateless_reasoning_forwarding(
    pg_client_echo, responses_factory: ResponsesFactory, make_test_agent
) -> None:
    """Request1 produces reasoning+assistant; Request2 should include reasoning in input."""
    agent, _client = await make_test_agent(pg_client_echo, [_make_reasoning_then_message("ok", responses_factory)])

    await agent.run("say hi")

    # Reasoning should be present in the agent transcript/messages for stateless forwarding
    assert_items_include_instances(agent.messages, ReasoningItem, AssistantMessage)


async def test_function_call_and_function_call_output_replay(
    pg_client_echo, responses_factory: ResponsesFactory, make_test_agent
) -> None:
    """Request1 produces a function_call; after local execution, messages() must include function_call and function_call_output."""
    agent, client = await make_test_agent(
        pg_client_echo,
        [
            responses_factory.make_mcp_tool_call("echo", "echo", EchoInput(text="hi")),
            _make_reasoning_then_message("done", responses_factory),
        ],
    )

    await agent.run("say hi")

    # Check that the captured second input includes function_call and function_call_output
    assert client.calls == 2
    input_items = list(client.captured[1].input or [])
    assert_items_include_instances(input_items, FunctionCallItem, FunctionCallOutputItem)


async def test_mixed_reasoning_fc_ordering(
    pg_client_echo, responses_factory: ResponsesFactory, make_test_agent
) -> None:
    """Resp1 returns reasoning, function_call, assistant; after function_call_output, messages preserves order
    reasoning, function_call, function_call_output, assistant.
    """
    # Note: .make() requires individual items; tool_call still uses build_mcp_function (justified)
    resp = responses_factory.make(
        responses_factory.make_item_reasoning(),
        responses_factory.mcp_tool_call("echo", "echo", EchoInput(text="hi")),
        responses_factory.assistant_text("done"),
    )
    agent, client = await make_test_agent(pg_client_echo, [resp, _make_reasoning_then_message("ok", responses_factory)])

    await agent.run("start")

    # Expect exactly two calls; validate second call input ordering/types
    assert client.calls == 2
    input_items = list(client.captured[1].input or [])
    assert_items_include_instances(
        input_items, ReasoningItem, FunctionCallItem, FunctionCallOutputItem, AssistantMessage
    )


async def test_no_synthesized_reasoning_items(
    pg_client_echo, responses_factory: ResponsesFactory, make_test_agent
) -> None:
    """Ensure agent does not fabricate reasoning rs_* items when missing."""
    agent, client = await make_test_agent(
        pg_client_echo,
        [
            responses_factory.make_mcp_tool_call("echo", "echo", EchoInput(text="hi")),
            _make_reasoning_then_message("done", responses_factory),
        ],
    )

    await agent.run("say hi")

    idx = min(1, len(client.captured) - 1)
    input_items = list(client.captured[idx].input or [])
    # No synthesized ReasoningItem entries should be present
    assert_items_exclude_instance(input_items, ReasoningItem)


async def test_model_provided_tool_output_records_without_execution(
    responses_factory: ResponsesFactory, pg_client_echo, make_test_agent
) -> None:
    """If the model supplies tool output inline, agent should not run the tool again."""
    agent, client = await make_test_agent(
        pg_client_echo,
        [responses_factory.make_mcp_tool_call_with_output("echo", "echo", EchoInput(text="hi"), {"echo": "hi"})],
    )

    await agent.run("say hi")

    assert_items_include_instances(agent.messages, FunctionCallOutputItem)
    assert not agent.pending_function_calls
    assert client.calls == 1
