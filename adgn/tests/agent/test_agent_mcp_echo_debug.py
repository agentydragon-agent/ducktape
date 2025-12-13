from __future__ import annotations

import pytest

from adgn.mcp.testing.simple_servers import EchoInput
from tests.support.steps import ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME


async def test_agent_mcp_echo_tool_use(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
    pg_client_echo,
    test_handlers,
    recording_handler,
    make_test_agent,
) -> None:
    agent, _client = await make_test_agent(
        pg_client_echo,
        [
            responses_factory.make_mcp_tool_call(ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput(text="hello")),
            responses_factory.make_assistant_message("done"),
        ],
        handlers=test_handlers,
        parallel_tool_calls=False,
    )

    res = await agent.run()

    # The tool output should be emitted (ToolCallOutput) and assistant text should follow
    outputs = [r for r in recording_handler.records if r.type == "function_call_output"]
    assert outputs, "No tool outputs captured"
    first = outputs[0]
    assert first.result.structuredContent == {"echo": "hello"}
    assert res.text.strip() == "done"
