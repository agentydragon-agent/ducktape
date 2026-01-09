from __future__ import annotations

from hamcrest import has_entries

from agent_core.agent import Agent
from agent_core.loop_control import RequireAnyTool
from agent_core_testing.matchers import assert_function_call_output_structured
from agent_core_testing.responses import EchoMock
from openai_utils.model import SystemMessage


async def test_agent_mcp_echo_tool_use(mcp_client_echo, test_handlers, recording_handler) -> None:
    @EchoMock.mock()
    def mock(m: EchoMock):
        yield
        yield from m.echo_roundtrip("hello")

    agent = await Agent.create(
        mcp_client=mcp_client_echo,
        client=mock,
        handlers=test_handlers,
        tool_policy=RequireAnyTool(),
        parallel_tool_calls=False,
    )
    agent.process_message(SystemMessage.text("test: use echo"))

    await agent.run()

    assert_function_call_output_structured(recording_handler.records, has_entries(echo="hello"))
