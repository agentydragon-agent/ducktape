from __future__ import annotations

import pytest
from hamcrest import has_entries

from agent_core.agent import Agent
from agent_core.loop_control import RequireAnyTool
from agent_core_testing.matchers import assert_function_call_output_structured
from agent_core_testing.openai_mock import LIVE
from agent_core_testing.responses import EchoMock
from openai_utils.model import BoundOpenAIModel, OpenAIModelProto, UserMessage


@pytest.mark.parametrize(
    "client_mode", [pytest.param("mock", id="mock"), pytest.param(LIVE, id="live", marks=pytest.mark.live_openai_api)]
)
async def test_minicodex_with_sdk_mocks_executes_tool_and_returns_text(
    responses_factory, live_openai, client_mode, mcp_client_echo, test_handlers, recording_handler
) -> None:
    # Responses sequence:
    # 1) Model asks to call echo.echo with {"text": "hi"}
    # 2) Model returns a final assistant message "done"
    client: OpenAIModelProto
    if client_mode is not LIVE:

        @EchoMock.mock()
        def mock(m: EchoMock):
            yield
            yield from m.echo_roundtrip("hi")
            yield m.assistant_text("done")

        client = mock
    else:
        client = BoundOpenAIModel(client=live_openai, model=responses_factory.model)

    agent = await Agent.create(
        mcp_client=mcp_client_echo, client=client, handlers=test_handlers, tool_policy=RequireAnyTool()
    )
    agent.process_message(UserMessage.text("say hi"))

    res = await agent.run()

    # Verify final text returned
    assert res.text.strip() == "done"
    # Verify the handler saw a function_call_output with the expected structured content
    assert_function_call_output_structured(recording_handler.records, has_entries(echo="hi"))
