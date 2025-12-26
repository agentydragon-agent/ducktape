from __future__ import annotations

from hamcrest import has_entries
import pytest

from agent_core.agent import Agent
from agent_core.loop_control import RequireAnyTool
from agent_core.testing import AssistantMessage, EchoCall, assert_function_call_output_structured
from openai_utils.model import SystemMessage


async def test_agent_mcp_echo_tool_use(
    monkeypatch: pytest.MonkeyPatch, mcp_client_echo, test_handlers, recording_handler, make_step_runner
) -> None:
    runner = make_step_runner(steps=[EchoCall("hello"), AssistantMessage("done")])
    agent = await Agent.create(
        mcp_client=mcp_client_echo,
        client=runner,
        handlers=test_handlers,
        tool_policy=RequireAnyTool(),
        parallel_tool_calls=False,
    )
    agent.insert_message(SystemMessage.text("test: use echo"))

    res = await agent.run()

    # The tool output should be emitted (ToolCallOutput) and assistant text should follow
    assert_function_call_output_structured(recording_handler.records, has_entries(echo="hello"))
    assert res.text.strip() == "done"
