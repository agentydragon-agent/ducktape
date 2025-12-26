from __future__ import annotations

from hamcrest import has_entries
import pytest

from agent_core.testing import FAIL_TOOL_NAME, assert_function_call_output_structured
from openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel


class FailInput(OpenAIStrictModeBaseModel):
    """Input for editor/fail tool (test fixture)."""

    x: int


async def test_app_level_error_payload_surfaced_in_structured_content(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
    compositor,
    compositor_client,
    error_payload_server,
    test_handlers,
    recording_handler,
    make_test_agent,
) -> None:
    """Test that application-level error payloads are surfaced in structuredContent.

    Note: This tests the {"ok": False, "error": "..."} pattern in structuredContent,
    NOT the MCP-level isError flag. For MCP-level error testing, see test_tool_error_continuation.
    """
    mounted = await compositor.mount_inproc("editor", error_payload_server)

    agent, _client = await make_test_agent(
        compositor_client,
        [
            responses_factory.make_mcp_tool_call(mounted.prefix, FAIL_TOOL_NAME, FailInput(x=1)),
            responses_factory.make_assistant_message("done"),
        ],
        handlers=test_handlers,
    )
    await agent.run()

    # Verify the application-level error payload is in structuredContent
    assert_function_call_output_structured(recording_handler.records, has_entries(ok=False, error="boom"))
