from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import AutoHandler
from adgn.mcp._shared.naming import build_mcp_function
from adgn.openai_utils.model import BoundOpenAIModel, OpenAIModelProto
from tests.agent.ws_helpers import assert_function_call_output_structured
from tests.llm.support.openai_mock import LIVE, FakeOpenAIModel


@pytest.mark.parametrize(
    "client_mode", [pytest.param("mock", id="mock"), pytest.param(LIVE, id="live", marks=pytest.mark.live_llm)]
)
async def test_minicodex_with_sdk_mocks_executes_tool_and_returns_text(
    responses_factory, live_openai, client_mode, pg_session_echo, recording_handler
) -> None:
    # Responses sequence:
    # 1) Model asks to call echo.echo with {"text": "hi"}
    # 2) Model returns a final assistant message "done"
    client: OpenAIModelProto
    if client_mode is not LIVE:
        client = FakeOpenAIModel(
            [
                responses_factory.make_tool_call(build_mcp_function("echo", "echo"), {"text": "hi"}),
                responses_factory.make_assistant_message("done"),
            ]
        )
    else:
        client = BoundOpenAIModel(client=live_openai, model=responses_factory.model)

    agent = await MiniCodex.create(
        model=responses_factory.model,
        mcp_client=pg_session_echo,
        system="test",
        client=client,
        handlers=[AutoHandler(), recording_handler],
    )

    res = await agent.run("say hi")

    # Verify final text returned
    assert res.text.strip() == "done"
    # Verify the handler saw a function_call_output with the expected structured content
    assert_function_call_output_structured(recording_handler.records, echo="hi")
