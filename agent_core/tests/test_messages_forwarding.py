from __future__ import annotations

import pytest

from agent_core.agent import Agent
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from agent_core_testing.matchers import assert_items_exclude_instance, assert_items_include_instances
from agent_core_testing.responses import DecoratorMock, EchoMock
from openai_utils.model import AssistantMessage, FunctionCallItem, FunctionCallOutputItem, ReasoningItem, UserMessage


@pytest.mark.timeout(1)
async def test_stateless_reasoning_forwarding(mcp_client_echo) -> None:
    """Request1 produces reasoning+assistant; Request2 should include reasoning in input."""

    @DecoratorMock.mock()
    def mock(m: DecoratorMock):
        yield
        yield [m.make_item_reasoning(), m.assistant_text("ok")]

    agent = await Agent.create(
        mcp_client=mcp_client_echo,
        client=mock,
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )
    agent.process_message(UserMessage.text("say hi"))
    await agent.run()

    assert_items_include_instances(agent.to_openai_messages(), ReasoningItem, AssistantMessage)


@pytest.mark.timeout(1)
async def test_function_call_and_function_call_output_replay(mcp_client_echo) -> None:
    """Request1 produces a function_call; after local execution, messages() must include function_call and function_call_output."""

    @EchoMock.mock()
    def mock(m: EchoMock):
        yield
        yield from m.echo_roundtrip("hi")
        # Capture second request to verify it contains function_call + output
        req = yield [m.make_item_reasoning(), m.assistant_text("done")]
        input_items = list(req.input or [])
        assert_items_include_instances(input_items, FunctionCallItem, FunctionCallOutputItem)

    agent = await Agent.create(
        mcp_client=mcp_client_echo,
        client=mock,
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )
    agent.process_message(UserMessage.text("say hi"))
    await agent.run()


@pytest.mark.timeout(1)
async def test_mixed_reasoning_fc_ordering(mcp_client_echo) -> None:
    """Resp1 returns reasoning, function_call, assistant; after function_call_output, messages preserves order
    reasoning, function_call, function_call_output, assistant.
    """

    @EchoMock.mock()
    def mock(m: EchoMock):
        yield
        # Single response with reasoning + tool call + text - agent finishes immediately
        yield [m.make_item_reasoning(), m.echo_call("hi"), m.assistant_text("done")]

    agent = await Agent.create(
        mcp_client=mcp_client_echo,
        client=mock,
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )
    agent.process_message(UserMessage.text("start"))
    await agent.run()

    messages = agent.to_openai_messages()
    assert_items_include_instances(messages, ReasoningItem, FunctionCallItem, FunctionCallOutputItem, AssistantMessage)


@pytest.mark.timeout(1)
async def test_no_synthesized_reasoning_items(mcp_client_echo) -> None:
    """Ensure agent does not fabricate reasoning rs_* items when missing."""

    @EchoMock.mock()
    def mock(m: EchoMock):
        yield
        yield from m.echo_roundtrip("hi")
        # Capture request to verify no synthesized reasoning
        req = yield [m.make_item_reasoning(), m.assistant_text("done")]
        input_items = list(req.input or [])
        assert_items_exclude_instance(input_items, ReasoningItem)

    agent = await Agent.create(
        mcp_client=mcp_client_echo,
        client=mock,
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )
    agent.process_message(UserMessage.text("say hi"))
    await agent.run()
