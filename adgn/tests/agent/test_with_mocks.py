from __future__ import annotations

from hamcrest import has_entries
import pytest

from adgn.agent.agent import Agent
from adgn.agent.loop_control import RequireAnyTool
from adgn.openai_utils.model import BoundOpenAIModel, OpenAIModelProto, UserMessage
from tests.agent.test_matchers import assert_function_call_output_structured
from tests.llm.support.openai_mock import LIVE
from tests.support.steps import AssistantMessage, EchoCall


@pytest.mark.parametrize(
    "client_mode", [pytest.param("mock", id="mock"), pytest.param(LIVE, id="live", marks=pytest.mark.live_llm)]
)
async def test_minicodex_with_sdk_mocks_executes_tool_and_returns_text(
    responses_factory, live_openai, client_mode, mcp_client_echo, test_handlers, recording_handler, make_step_runner
) -> None:
    # Responses sequence:
    # 1) Model asks to call echo.echo with {"text": "hi"}
    # 2) Model returns a final assistant message "done"
    client: OpenAIModelProto
    if client_mode is not LIVE:
        runner = make_step_runner(steps=[EchoCall("hi"), AssistantMessage("done")])
        client = runner  # _StepRunner implements OpenAIModelProto directly
    else:
        client = BoundOpenAIModel(client=live_openai, model=responses_factory.model)

    agent = await Agent.create(
        mcp_client=mcp_client_echo, client=client, handlers=test_handlers, tool_policy=RequireAnyTool()
    )
    agent.insert_message(UserMessage.text("say hi"))

    res = await agent.run()

    # Verify final text returned
    assert res.text.strip() == "done"
    # Verify the handler saw a function_call_output with the expected structured content
    assert_function_call_output_structured(recording_handler.records, has_entries(echo="hi"))
