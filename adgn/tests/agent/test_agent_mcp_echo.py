from __future__ import annotations

import pytest

from adgn.agent.reducer import AutoHandler
from adgn.mcp._shared.naming import build_mcp_function


async def test_agent_mcp_echo_tool_use(
    monkeypatch: pytest.MonkeyPatch, responses_factory, pg_session_echo, recording_handler, make_test_agent
) -> None:
    agent, client = await make_test_agent(
        pg_session_echo,
        [
            responses_factory.make_tool_call(build_mcp_function("echo", "echo"), {"text": "hello"}),
            responses_factory.make_assistant_message("done"),
        ],
        handlers=[AutoHandler(), recording_handler],
        parallel_tool_calls=False,
    )

    async with agent:
        res = await agent.run(user_text="use echo")

    # The tool output should be emitted (ToolCallOutput) and assistant text should follow
    outputs = [r for r in recording_handler.records if r.get("kind") == "function_call_output"]
    assert outputs, "No tool outputs captured"
    first = outputs[0]
    assert first["result"]["structured_content"] == {"echo": "hello"}
    assert res.text.strip() == "done"
