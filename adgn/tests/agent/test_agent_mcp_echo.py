from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.loggers import RecordingHandler
from adgn.agent.reducer import AutoHandler
from adgn.mcp._shared.naming import build_mcp_function
from tests.llm.support.openai_mock import FakeOpenAIModel


async def test_agent_mcp_echo_tool_use(
    monkeypatch: pytest.MonkeyPatch, responses_factory, make_pg_compositor_echo
) -> None:
    # Provide a two-step sequence via our shared Pydantic fake client
    client = FakeOpenAIModel(
        [
            responses_factory.make_tool_call(build_mcp_function("echo", "echo"), {"text": "hello"}),
            responses_factory.make_assistant_message("done"),
        ]
    )

    rec = RecordingHandler()

    async with make_pg_compositor_echo() as (mcp_client, _comp):
        agent = await MiniCodex.create(
            model="test-model",
            mcp_client=mcp_client,
            system="You are a test agent.",
            client=client,
            handlers=[AutoHandler(), rec],
            parallel_tool_calls=False,
        )
        async with agent:
            res = await agent.run(user_text="use echo")

    # The tool output should be emitted (ToolCallOutput) and assistant text should follow
    outputs = [r for r in rec.records if r.get("kind") == "function_call_output"]
    assert outputs, "No tool outputs captured"
    first = outputs[0]
    assert first["result"]["structured_content"] == {"echo": "hello"}
    assert res.text.strip() == "done"
