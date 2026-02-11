from __future__ import annotations

from pydantic import BaseModel
import pytest

from tests.agent.test_matchers import assert_function_call_output_structured


class FailInput(BaseModel):
    """Input for editor/fail tool (test fixture)."""

    x: int


async def test_tool_error_is_surfaced_in_sequence(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
    make_pg_client,
    failing_server,
    recording_handler,
    make_test_agent,
) -> None:
    async with make_pg_client({"editor": failing_server}) as mcp_client:
        agent, _client = await make_test_agent(
            mcp_client,
            [
                responses_factory.make_mcp_tool_call("editor", "fail", FailInput(x=1)),
                responses_factory.make_assistant_message("done"),
            ],
            handlers=[recording_handler],
        )
        await agent.run("call failing tool once")

    # Extract the function_call_output from the recording handler and assert failure payload surfaced
    assert_function_call_output_structured(recording_handler.records, ok=False, error="boom")
