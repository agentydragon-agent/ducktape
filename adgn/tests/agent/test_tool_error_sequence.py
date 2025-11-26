from __future__ import annotations

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import AutoHandler
from adgn.mcp._shared.naming import build_mcp_function
from tests.agent.ws_helpers import assert_function_call_output_structured
from tests.llm.support.openai_mock import FakeOpenAIModel


async def test_tool_error_is_surfaced_in_sequence(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
    make_pg_session,
    approval_policy_reader_allow_all,
    failing_server,
    recording_handler,
) -> None:
    async with make_pg_session(
        {"editor": failing_server, "approval_policy": approval_policy_reader_allow_all}
    ) as mcp_client:
        client = FakeOpenAIModel(
            [
                responses_factory.make_tool_call(build_mcp_function("editor", "fail"), {"x": 1}),
                responses_factory.make_assistant_message("done"),
            ]
        )
        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp_client=mcp_client,
            system="You are a code agent.",
            client=client,
            handlers=[AutoHandler(), recording_handler],
        )
        await agent.run("call failing tool once")

    # Extract the function_call_output from the recording handler and assert failure payload surfaced
    assert_function_call_output_structured(recording_handler.records, ok=False, error="boom")
