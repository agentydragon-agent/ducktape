from __future__ import annotations

from fastmcp import Context
from fastmcp.server import FastMCP
from pydantic import BaseModel, ConfigDict
import pytest

from adgn.agent.agent import Agent
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.notifications.handler import NotificationsHandler
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp._shared.types import MCPMountPrefix, SimpleOk
from adgn.mcp._shared.urls import parse_any_url
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.stubs.typed_stubs import ToolStub

# Note: build_mcp_function still needed for ToolStub construction (line 66) and direct call_tool (line 159)
from adgn.openai_utils.model import InputTextPart, ResponsesRequest, ResponsesResult, UserMessage
from tests.llm.support.openai_mock import make_mock
from tests.support.responses import ResponsesFactory

# Test MCP server/tool constants for this test
NOTIFIER_MOUNT_PREFIX = MCPMountPrefix("notifier")
NOTIFY_POLICY_TOOL_NAME = "notify_policy"


class NotifyPolicyInput(BaseModel):
    uri: str
    model_config = ConfigDict(extra="forbid")


class NotifyPolicyOutput(BaseModel):
    ok: bool
    uri: str
    model_config = ConfigDict(extra="forbid")


class PrimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _NotifierServer(EnhancedFastMCP):
    """Test helper EnhancedFastMCP that can emit resource-updated notifications via a callback.

    Emits ResourceUpdated notifications via the protocol inside tool logic.
    """

    def __init__(self) -> None:
        super().__init__(name="notifier", instructions="Test notifier server")

        @self.flat_model()
        async def notify_policy(input: NotifyPolicyInput, context: Context) -> NotifyPolicyOutput:
            # Protocol-level notification: emit ResourceUpdatedNotification from server to client
            assert context.request_context is not None, "request_context must be present in tool handler"
            sess = context.request_context.session  # low-level ServerSession
            await sess.send_resource_updated(parse_any_url(input.uri))
            return NotifyPolicyOutput(ok=True, uri=input.uri)


@pytest.fixture
def server() -> FastMCP:
    return _NotifierServer()


def _has_notification_with_substring(req: ResponsesRequest, substring: str) -> bool:
    """Check if a request has a system notification containing the given substring."""
    for msg in req.input or []:
        if isinstance(msg, UserMessage):
            for c in msg.content or []:
                if isinstance(c, InputTextPart) and "<system notification>" in c.text:
                    payload = c.text.split("\n", 1)[-1]
                    if substring in payload:
                        return True
    return False


async def _make_agent_with_notifications(mcp_client, buf, client):
    """Helper to create agent with NotificationsHandler wired."""
    return await Agent.create(
        mcp_client=mcp_client, handlers=[NotificationsHandler(buf.poll)], client=client, tool_policy=RequireAnyTool()
    )


@pytest.mark.skip(
    reason="Hangs under pytest-xdist due to importlib.metadata.version('mcp') calling os.stat() "
    "during FastMCP server initialization. Likely race condition in metadata caching. "
    "Also previously had issues with Pydantic serialization in CapturingOpenAIModel (now fixed). "
    "See: tests/llm/support/openai_mock.py for serialization fix."
)
async def test_notifications_pre_sampling_out_of_band(
    server: FastMCP, responses_factory: ResponsesFactory, make_buffered_client
) -> None:
    # Buffered client path via shared fixture
    async with make_buffered_client({"notifier": server}) as (mcp_client, _comp, buf):
        # Prime a protocol-level notification before sampling by calling the server tool once
        stub = ToolStub(mcp_client, build_mcp_function(NOTIFIER_MOUNT_PREFIX, "notify_policy"), NotifyPolicyOutput)
        await stub(NotifyPolicyInput(uri="notifier://policy.py"))

        captured: list[ResponsesRequest] = []

        async def _create(req: ResponsesRequest) -> ResponsesResult:
            captured.append(req)
            result: ResponsesResult = responses_factory.make_assistant_message("ok")
            return result

        client = make_mock(_create)
        agent = await _make_agent_with_notifications(mcp_client, buf, client)
        agent.insert_message(UserMessage.text("hello"))
        await agent.run()

        # Inspect the input passed to Responses.create; expect a system notification insert
        assert captured, "expected at least one responses.create call"
        assert any(_has_notification_with_substring(req, "policy.py") for req in captured), (
            "expected system notification in request input"
        )


async def test_notifications_within_turn_from_tool(
    server: FastMCP, responses_factory: ResponsesFactory, make_buffered_client
):
    # Build notifier server and manager
    stage = {"n": 0}
    captured: list[ResponsesRequest] = []

    async def _create(req: ResponsesRequest) -> ResponsesResult:
        captured.append(req)
        stage["n"] += 1
        if stage["n"] == 1:
            # First model output: ask to call notifier.notify_policy
            tool_call_result: ResponsesResult = responses_factory.make_mcp_tool_call(
                NOTIFIER_MOUNT_PREFIX, NOTIFY_POLICY_TOOL_NAME, NotifyPolicyInput(uri="notifier://policy.py")
            )
            return tool_call_result
        # Second (and later) model output: nothing else to do
        assistant_result: ResponsesResult = responses_factory.make_assistant_message("done")
        return assistant_result

    async with make_buffered_client({"notifier": server}) as (mcp_client, _comp, buf):
        client = make_mock(_create)
        agent = await _make_agent_with_notifications(mcp_client, buf, client)
        agent.insert_message(UserMessage.text("go"))
        await agent.run()

        # The second create call (post-tool) should include the injected system notification
        assert len(captured) >= 2, "expected at least two sampling calls"
        assert _has_notification_with_substring(captured[-1], "policy.py"), (
            "expected system notification after tool-triggered update"
        )


async def test_notifications_broadcast_outside_tool(responses_factory: ResponsesFactory, make_buffered_client):
    # Server that can broadcast notifications outside a tool
    server = EnhancedFastMCP(name="notifier", instructions="Notifier test")

    @server.tool()
    async def prime(input: PrimeInput) -> SimpleOk:
        return SimpleOk()

    # no server specs needed for this test
    captured: list[ResponsesRequest] = []

    async def _create(req: ResponsesRequest) -> ResponsesResult:
        captured.append(req)
        result: ResponsesResult = responses_factory.make_assistant_message("ok")
        return result

    async with make_buffered_client({"notifier": server}) as (mcp_client, _comp, buf):
        # Establish session (prime) then broadcast outside any tool handler
        await mcp_client.call_tool(name=build_mcp_function(NOTIFIER_MOUNT_PREFIX, "prime"), arguments={})
        await server.broadcast_resource_updated("notifier://policy.py")

        client = make_mock(_create)
        agent = await _make_agent_with_notifications(mcp_client, buf, client)
        agent.insert_message(UserMessage.text("hello"))
        await agent.run()

        # Expect notification inserted before sampling
        assert any(_has_notification_with_substring(req, "policy.py") for req in captured), (
            "expected system notification after out-of-tool broadcast"
        )
