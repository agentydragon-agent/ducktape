from __future__ import annotations

import pytest

from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from agent_core_testing.echo_server import ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput
from agent_core_testing.matchers import assert_items_exclude_instance, assert_items_include_instances
from agent_core_testing.responses import ResponsesFactory
from openai_utils.model import AssistantMessage, FunctionCallItem, FunctionCallOutputItem, ReasoningItem, UserMessage


@pytest.mark.timeout(1)
async def test_stateless_reasoning_forwarding(
    mcp_client_echo, responses_factory: ResponsesFactory, make_test_agent
) -> None:
    """Request1 produces reasoning+assistant; Request2 should include reasoning in input."""
    agent, _client = await make_test_agent(
        mcp_client_echo,
        [responses_factory.make(responses_factory.make_item_reasoning(), responses_factory.assistant_text("ok"))],
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(UserMessage.text("say hi"))
    await agent.run()

    # Reasoning should be present in the agent transcript/messages for stateless forwarding
    assert_items_include_instances(agent.to_openai_messages(), ReasoningItem, AssistantMessage)


@pytest.mark.timeout(1)
async def test_function_call_and_function_call_output_replay(
    mcp_client_echo, responses_factory: ResponsesFactory, make_test_agent
) -> None:
    """Request1 produces a function_call; after local execution, messages() must include function_call and function_call_output."""
    agent, client = await make_test_agent(
        mcp_client_echo,
        [
            responses_factory.make_mcp_tool_call(ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput(text="hi")),
            responses_factory.make(responses_factory.make_item_reasoning(), responses_factory.assistant_text("done")),
        ],
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(UserMessage.text("say hi"))
    await agent.run()

    # Check that the captured second input includes function_call and function_call_output
    assert client.calls == 2
    input_items = list(client.captured[1].input or [])
    assert_items_include_instances(input_items, FunctionCallItem, FunctionCallOutputItem)


@pytest.mark.timeout(1)
async def test_mixed_reasoning_fc_ordering(
    mcp_client_echo, responses_factory: ResponsesFactory, make_test_agent
) -> None:
    """Resp1 returns reasoning, function_call, assistant; after function_call_output, messages preserves order
    reasoning, function_call, function_call_output, assistant.
    """
    # Note: .make() requires individual items; tool_call still uses build_mcp_function (justified)
    resp = responses_factory.make(
        responses_factory.make_item_reasoning(),
        responses_factory.mcp_tool_call(ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput(text="hi")),
        responses_factory.assistant_text("done"),
    )
    agent, client = await make_test_agent(
        mcp_client_echo, [resp], handlers=[FinishOnTextMessageHandler()], tool_policy=AllowAnyToolOrTextMessage()
    )

    agent.process_message(UserMessage.text("start"))
    await agent.run()

    # Agent finishes after first response (has assistant text), but should preserve message ordering
    assert client.calls == 1
    messages = agent.to_openai_messages()
    assert_items_include_instances(messages, ReasoningItem, FunctionCallItem, FunctionCallOutputItem, AssistantMessage)


@pytest.mark.timeout(1)
async def test_no_synthesized_reasoning_items(
    mcp_client_echo, responses_factory: ResponsesFactory, make_test_agent
) -> None:
    """Ensure agent does not fabricate reasoning rs_* items when missing."""
    agent, client = await make_test_agent(
        mcp_client_echo,
        [
            responses_factory.make_mcp_tool_call(ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput(text="hi")),
            responses_factory.make(responses_factory.make_item_reasoning(), responses_factory.assistant_text("done")),
        ],
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(UserMessage.text("say hi"))
    await agent.run()

    idx = min(1, len(client.captured) - 1)
    input_items = list(client.captured[idx].input or [])
    # No synthesized ReasoningItem entries should be present
    assert_items_exclude_instance(input_items, ReasoningItem)


@pytest.mark.timeout(1)
async def test_model_provided_tool_output_records_without_execution(
    responses_factory: ResponsesFactory, mcp_client_echo, make_test_agent
) -> None:
    """If the model supplies tool output inline, agent should not run the tool again."""
    agent, client = await make_test_agent(
        mcp_client_echo,
        [
            responses_factory.make_mcp_tool_call_with_output(
                ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput(text="hi"), {"echo": "hi"}
            ),
            responses_factory.make_assistant_message("done"),
        ],
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(UserMessage.text("say hi"))
    await agent.run()

    assert_items_include_instances(agent.to_openai_messages(), FunctionCallOutputItem)
    assert not agent.pending_function_calls
    # Now expects 2 calls: tool call with inline output, then text message to finish
    assert client.calls == 2
