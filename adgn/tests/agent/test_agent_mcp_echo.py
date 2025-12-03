from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp.testing.simple_servers import EchoInput
from tests.agent.test_matchers import assert_function_call_output_structured
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import AssistantMessage, MakeCall


async def test_agent_mcp_echo_tool_use(
    monkeypatch: pytest.MonkeyPatch, pg_client_echo, recording_handler, make_step_runner
) -> None:
    runner = make_step_runner(steps=[MakeCall("echo", "echo", EchoInput(text="hello")), AssistantMessage("done")])
    client = make_mock(runner.handle_request_async)
    agent = await MiniCodex.create(
        mcp_client=pg_client_echo,
        system="test",
        client=client,
        handlers=[recording_handler],
        tool_policy=RequireAnyTool(),
        parallel_tool_calls=False,
    )

    async with agent:
        res = await agent.run(user_text="use echo")

    # The tool output should be emitted (ToolCallOutput) and assistant text should follow
    assert_function_call_output_structured(recording_handler.records, echo="hello")
    assert res.text.strip() == "done"
