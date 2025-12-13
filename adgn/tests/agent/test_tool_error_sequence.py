from __future__ import annotations

from hamcrest import has_entries
import pytest

from adgn.mcp.editor_server import EditorServer
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from tests.agent.test_matchers import assert_function_call_output_structured
from tests.support.steps import FAIL_TEST_TOOL_NAME


class FailInput(OpenAIStrictModeBaseModel):
    """Input for editor/fail tool (test fixture)."""

    x: int


async def test_tool_error_is_surfaced_in_sequence(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
    make_pg_client,
    failing_server,
    test_handlers,
    recording_handler,
    make_test_agent,
) -> None:
    async with make_pg_client({"editor": failing_server}) as mcp_client:
        agent, _client = await make_test_agent(
            mcp_client,
            [
                responses_factory.make_mcp_tool_call(
                    EditorServer.DEFAULT_MOUNT_PREFIX, FAIL_TEST_TOOL_NAME, FailInput(x=1)
                ),
                responses_factory.make_assistant_message("done"),
            ],
            handlers=test_handlers,
        )
        await agent.run()

    # Extract the function_call_output from the recording handler and assert failure payload surfaced
    assert_function_call_output_structured(recording_handler.records, has_entries(ok=False, error="boom"))
