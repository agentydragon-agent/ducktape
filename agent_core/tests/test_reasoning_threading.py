from __future__ import annotations

from hamcrest import assert_that, has_item, has_properties, instance_of, not_

from agent_core.agent import Agent
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from agent_core_testing.echo_server import ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput
from agent_core_testing.responses import DecoratorMock
from mcp_infra.naming import build_mcp_function
from openai_utils.model import FunctionCallItem, FunctionCallOutputItem, ReasoningItem, UserMessage


async def test_reasoning_threading_filters_reasoning_from_next_input(mcp_client_echo) -> None:
    """Test that reasoning items are properly threaded with their function calls across turns."""

    @DecoratorMock.mock()
    def mock(m: DecoratorMock):
        # Create function calls with explicit id and status to verify preservation
        fc1 = FunctionCallItem(
            name=build_mcp_function(ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME),
            arguments=EchoInput(text="hi").model_dump_json(),
            call_id="call_1",
            id="fc_id_1",
            status="completed",
        )
        fc2 = FunctionCallItem(
            name=build_mcp_function(ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME),
            arguments=EchoInput(text="bye").model_dump_json(),
            call_id="call_2",
            id="fc_id_2",
            status="in_progress",
        )

        # Turn 1: initial request should have user message but no reasoning
        req1 = yield
        turn1_input = list(req1.input or [])
        assert_that(turn1_input, has_item(instance_of(UserMessage)))
        assert_that(turn1_input, not_(has_item(instance_of(ReasoningItem))))

        # Turn 2: should include turn 1's reasoning + tool call + output
        req2 = yield [m.make_item_reasoning(id="rs_turn1"), fc1]
        turn2_input = list(req2.input or [])
        assert_that(turn2_input, has_item(has_properties(id="rs_turn1")))
        assert_that(turn2_input, has_item(has_properties(call_id="call_1", id="fc_id_1", status="completed")))
        assert_that(turn2_input, has_item(instance_of(FunctionCallOutputItem) & has_properties(call_id="call_1")))

        # Turn 3: should include both turns' sequences
        req3 = yield [m.make_item_reasoning(id="rs_turn2"), fc2]
        turn3_input = list(req3.input or [])
        # Turn 1's sequence still intact
        assert_that(turn3_input, has_item(has_properties(id="rs_turn1")))
        assert_that(turn3_input, has_item(has_properties(call_id="call_1", id="fc_id_1")))
        assert_that(turn3_input, has_item(instance_of(FunctionCallOutputItem) & has_properties(call_id="call_1")))
        # Turn 2's sequence
        assert_that(turn3_input, has_item(has_properties(id="rs_turn2")))
        assert_that(turn3_input, has_item(has_properties(call_id="call_2", id="fc_id_2", status="in_progress")))
        assert_that(turn3_input, has_item(instance_of(FunctionCallOutputItem) & has_properties(call_id="call_2")))

        yield m.assistant_text("done")

    agent = await Agent.create(
        mcp_client=mcp_client_echo,
        client=mock,
        handlers=[FinishOnTextMessageHandler()],
        tool_policy=AllowAnyToolOrTextMessage(),
    )
    agent.process_message(UserMessage.text("say hi"))

    res = await agent.run()
    assert res.text.strip() == "done"
