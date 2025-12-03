from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp.testing.simple_servers import EchoInput
from adgn.openai_utils.model import BoundOpenAIModel, OpenAIModelProto
from tests.agent.test_matchers import assert_function_call_output_structured
from tests.llm.support.openai_mock import LIVE, make_mock
from tests.support.steps import AssistantMessage, MakeCall


@pytest.mark.parametrize(
    "client_mode", [pytest.param("mock", id="mock"), pytest.param(LIVE, id="live", marks=pytest.mark.live_llm)]
)
async def test_minicodex_with_sdk_mocks_executes_tool_and_returns_text(
    responses_factory, live_openai, client_mode, pg_client_echo, recording_handler, make_step_runner
) -> None:
    # Responses sequence:
    # 1) Model asks to call echo.echo with {"text": "hi"}
    # 2) Model returns a final assistant message "done"
    client: OpenAIModelProto
    if client_mode is not LIVE:
        runner = make_step_runner(steps=[MakeCall("echo", "echo", EchoInput(text="hi")), AssistantMessage("done")])
        client = make_mock(runner.handle_request_async)
    else:
        client = BoundOpenAIModel(client=live_openai, model=responses_factory.model)

    agent = await MiniCodex.create(
        mcp_client=pg_client_echo,
        system="test",
        client=client,
        handlers=[recording_handler],
        tool_policy=RequireAnyTool(),
    )

    res = await agent.run("say hi")

    # Verify final text returned
    assert res.text.strip() == "done"
    # Verify the handler saw a function_call_output with the expected structured content
    assert_function_call_output_structured(recording_handler.records, echo="hi")
