from __future__ import annotations

from hamcrest import has_entries

from agent_core.agent import Agent
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from agent_core_testing.fixtures import FAIL_TOOL_NAME
from agent_core_testing.matchers import assert_function_call_output_structured
from agent_core_testing.responses import DecoratorMock
from mcp_infra.naming import build_mcp_function
from mcp_infra.prefix import MCPMountPrefix
from openai_utils.model import UserMessage
from openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel


class FailInput(OpenAIStrictModeBaseModel):
    """Input for editor/fail tool (test fixture)."""

    x: int


async def test_app_level_error_payload_surfaced_in_structured_content(
    compositor, compositor_client, error_payload_server, recording_handler
) -> None:
    """Test that application-level error payloads are surfaced in structuredContent.

    Note: This tests the {"ok": False, "error": "..."} pattern in structuredContent,
    NOT the MCP-level isError flag. For MCP-level error testing, see test_tool_error_continuation.
    """
    mounted = await compositor.mount_inproc(MCPMountPrefix("editor"), error_payload_server)

    @DecoratorMock.mock()
    def mock(m: DecoratorMock):
        yield
        yield m.tool_call(build_mcp_function(mounted.prefix, FAIL_TOOL_NAME), FailInput(x=1))
        yield m.assistant_text("done")

    agent = await Agent.create(
        mcp_client=compositor_client,
        client=mock,
        handlers=[FinishOnTextMessageHandler(), recording_handler],
        tool_policy=AllowAnyToolOrTextMessage(),
    )
    agent.process_message(UserMessage.text("fail"))
    await agent.run()

    assert_function_call_output_structured(recording_handler.records, has_entries(ok=False, error="boom"))
