from __future__ import annotations

from hamcrest import has_entries
import pytest

from adgn.agent.agent import Agent
from adgn.agent.loop_control import RequireAnyTool
from adgn.openai_utils.model import SystemMessage
from tests.agent.test_matchers import assert_function_call_output_structured
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import AssistantMessage, EchoCall


async def test_agent_mcp_echo_tool_use(
    monkeypatch: pytest.MonkeyPatch, pg_client_echo, test_handlers, recording_handler, make_step_runner
) -> None:
    runner = make_step_runner(steps=[EchoCall("hello"), AssistantMessage("done")])
    client = make_mock(runner.handle_request_async)
    agent = await Agent.create(
        mcp_client=pg_client_echo,
        client=client,
        handlers=test_handlers,
        tool_policy=RequireAnyTool(),
        parallel_tool_calls=False,
    )
    agent.insert_message(SystemMessage.text("test: use echo"))

    res = await agent.run()

    # The tool output should be emitted (ToolCallOutput) and assistant text should follow
    assert_function_call_output_structured(recording_handler.records, has_entries(echo="hello"))
    assert res.text.strip() == "done"
