from __future__ import annotations

from hamcrest import has_entries
import pytest

from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from tests.agent.test_matchers import assert_function_call_output_structured
from tests.support.steps import FAIL_TEST_TOOL_NAME


class FailInput(OpenAIStrictModeBaseModel):
    """Input for editor/fail tool (test fixture)."""

    x: int


async def test_tool_error_is_surfaced_in_sequence(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
    compositor,
    compositor_client,
    failing_server,
    test_handlers,
    recording_handler,
    make_test_agent,
) -> None:
    """Test that tool errors are surfaced in the sequence without policy gateway."""
    # Mount failing server and capture Mounted object
    mounted_failing = await compositor.mount_inproc("editor", failing_server)

    # Use compositor_client fixture
    agent, _client = await make_test_agent(
        compositor_client,
        [
            responses_factory.make_mcp_tool_call(mounted_failing.prefix, FAIL_TEST_TOOL_NAME, FailInput(x=1)),
            responses_factory.make_assistant_message("done"),
        ],
        handlers=test_handlers,
    )
    await agent.run()

    # Extract the function_call_output from the recording handler and assert failure payload surfaced
    assert_function_call_output_structured(recording_handler.records, has_entries(ok=False, error="boom"))
