from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict
import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.mcp_manager import McpManager
from adgn.agent.reducer import AutoHandler, NotificationsHandler
from adgn.mcp._shared.fastmcp_helpers import mcp_flat_model
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.mcp.testing.typed_stubs import TypedClient
from adgn.openai_utils.model import (
    InputTextPart,
    ResponsesRequest,
    ResponsesResult,
    UserMessage,
)
from tests.llm.support.openai_mock import make_mock


class NotifyPolicyInput(BaseModel):
    uri: str = "notifier://policy.py"
    model_config = ConfigDict(extra="forbid")


class NotifyPolicyOutput(BaseModel):
    ok: bool
    uri: str
    model_config = ConfigDict(extra="forbid")


class _NotifierServer(FastMCP):
    """Test helper FastMCP that can emit resource-updated notifications via a callback.

    We attach a _notify(uri: str) callable post-construction that is expected to call
    McpManager.notify_resource_updated("notifier", uri). Tools can then trigger it.
    """

    def __init__(self) -> None:
        super().__init__(name="notifier", instructions="Test notifier server")

        @mcp_flat_model(
            self,
            name="notify_policy",
            title="Notify policy",
            description="Emit a ResourceUpdated notification",
            structured_output=True,
        )
        async def notify_policy(input: NotifyPolicyInput) -> NotifyPolicyOutput:
            # Protocol-level notification: emit ResourceUpdatedNotification from server to client
            ctx = self.get_context()
            sess = ctx.request_context.session  # low-level ServerSession
            await sess.send_resource_updated(input.uri)
            return NotifyPolicyOutput(ok=True, uri=input.uri)


@pytest.fixture
def server() -> FastMCP:
    return _NotifierServer()


@pytest.mark.asyncio
async def test_notifications_pre_sampling_out_of_band(
    server: FastMCP,
    responses_factory,
):
    # Build notifier server and manager
    async with McpManager({}) as mcp:
        await mcp.attach_server("notifier", make_inproc_slot_spec(server))
        # Prime a protocol-level notification before sampling by calling the server tool once
        # (establishes session and emits ResourceUpdatedNotification)
        sess = await mcp.get_session("notifier")
        # Use typed client to call the tool with default args
        client = TypedClient.from_server(server, sess)
        await client.notify_policy(NotifyPolicyInput())

        captured: list[ResponsesRequest] = []

        async def _create(req: ResponsesRequest) -> ResponsesResult:
            captured.append(req)
            # Minimal assistant response; we only care about the input we sent
            return responses_factory.make_assistant_message("ok")

        client = make_mock(_create)
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            handlers=[NotificationsHandler(mcp), AutoHandler()],
            client=client,
            system="n/a",
        )
        await agent.run("hello")

        # Inspect the input passed to Responses.create; expect a system notification insert
        assert captured, "expected at least one responses.create call"

        def _has_sysfyi(req: ResponsesRequest) -> bool:
            inp = req.input or []
            for msg in inp:
                if isinstance(msg, UserMessage):
                    for c in msg.content or []:
                        if isinstance(c, InputTextPart) and "<system notification>" in c.text:
                            payload = c.text.split("\n", 1)[-1]
                            if "notifier" in payload and "policy.py" in payload:
                                return True
            return False

        assert any(_has_sysfyi(req) for req in captured), (
            "expected system notification in request input"
        )


@pytest.mark.asyncio
async def test_notifications_within_turn_from_tool(
    server: FastMCP,
    responses_factory,
):
    # Build notifier server and manager
    stage = {"n": 0}
    captured: list[ResponsesRequest] = []

    async def _create(req: ResponsesRequest) -> ResponsesResult:
        captured.append(req)
        stage["n"] += 1
        if stage["n"] == 1:
            # First model output: ask to call notifier.notify_policy
            return responses_factory.make_tool_call("mcp__notifier__notify_policy", {})
        # Second (and later) model output: nothing else to do
        return responses_factory.make_assistant_message("done")

    async with McpManager({}) as mcp:
        await mcp.attach_server("notifier", make_inproc_slot_spec(server))
        client = make_mock(_create)
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            handlers=[NotificationsHandler(mcp), AutoHandler()],
            client=client,
            system="n/a",
        )
        await agent.run("go")

        # The second create call (post-tool) should include the injected system notification
        assert len(captured) >= 2, "expected at least two sampling calls"
        second = captured[-1]
        found = False
        for msg in second.input or []:
            if isinstance(msg, UserMessage):
                for c in msg.content or []:
                    if isinstance(c, InputTextPart) and "<system notification>" in c.text:
                        found = True
                        break
            if found:
                break
        assert found, "expected system notification after tool-triggered update"


@pytest.mark.asyncio
async def test_notifications_broadcast_outside_tool(responses_factory):
    # Server that can broadcast notifications outside a tool
    server = NotifyingFastMCP(name="notifier", instructions="Notifier test")

    @server.tool()
    async def prime() -> dict[str, Any]:
        return {"ok": True}

    # no server specs needed for this test
    captured: list[ResponsesRequest] = []

    async def _create(req: ResponsesRequest) -> ResponsesResult:
        captured.append(req)
        return responses_factory.make_assistant_message("ok")

    async with McpManager({}) as mcp:
        await mcp.attach_server("notifier", make_inproc_slot_spec(server))
        # Establish a session (prime capture) then broadcast outside any tool handler
        sess = await mcp.get_session("notifier")
        await sess.call_tool(name="prime", arguments={})
        await server.broadcast_resource_updated("notifier://policy.py")

        client = make_mock(_create)
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mcp,
            handlers=[NotificationsHandler(mcp), AutoHandler()],
            client=client,
            system="n/a",
        )
        await agent.run("hello")

        # Expect notification inserted before sampling
        def _has_sysfyi(req: ResponsesRequest) -> bool:
            for msg in req.input or []:
                if isinstance(msg, UserMessage):
                    for c in msg.content or []:
                        if isinstance(c, InputTextPart) and "<system notification>" in c.text:
                            payload = c.text.split("\n", 1)[-1]
                            if "notifier" in payload and "policy.py" in payload:
                                return True
            return False

        assert any(_has_sysfyi(req) for req in captured), (
            "expected system notification after out-of-tool broadcast"
        )
