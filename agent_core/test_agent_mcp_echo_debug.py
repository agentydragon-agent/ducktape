from __future__ import annotations

from agent_core.agent import Agent
from agent_core.loop_control import RequireAnyTool
from agent_core_testing.responses import EchoMock
from openai_utils.model import UserMessage


async def test_agent_mcp_echo_tool_use(mcp_client_echo, test_handlers, recording_handler) -> None:
    @EchoMock.mock()
    def mock(m: EchoMock):
        yield
        yield from m.echo_roundtrip("hello")
        yield m.assistant_text("done")

    agent = await Agent.create(
        mcp_client=mcp_client_echo, client=mock, handlers=test_handlers, tool_policy=RequireAnyTool()
    )
    agent.process_message(UserMessage.text("say hello"))

    res = await agent.run()

    outputs = [r for r in recording_handler.records if r.type == "function_call_output"]
    assert outputs, "No tool outputs captured"
    assert outputs[0].result.structuredContent == {"echo": "hello"}
    assert res.text.strip() == "done"
