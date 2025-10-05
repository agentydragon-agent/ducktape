from __future__ import annotations

from mcp import types as mcp_types
import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.handler import (
    AbortTurnDecision,
    BypassToolInjectOutput,
    ToolCall,
)
from adgn.agent.loggers import RecordingHandler
from adgn.agent.mcp_manager import McpManager
from adgn.agent.reducer import AutoHandler
from adgn.openai_utils.model import FakeOpenAIModel
from tests.agent.ws_helpers import assert_function_call_output_structured


class InjectHandler(AutoHandler):
    def __init__(self, result: mcp_types.CallToolResult | None):
        super().__init__()
        self._result = result

    async def before_tool_call(self, evt: ToolCall) -> BypassToolInjectOutput | None:
        # Intercept the specific spy echo call
        if evt.name.endswith("__echo"):
            return BypassToolInjectOutput(result=self._result)
        return None


class AbortHandler(AutoHandler):
    async def before_tool_call(self, evt: ToolCall) -> AbortTurnDecision | None:
        if evt.name.endswith("__echo"):
            return AbortTurnDecision(reason="test-deny")
        return None


@pytest.mark.asyncio
async def test_before_tool_call_inject_result_does_not_call_underlying_tool(
    fake_openai_client_factory,
    responses_factory,
    make_spy_spec,
) -> None:
    counter: list[str] = []
    specs = make_spy_spec(counter)

    seq = [
        responses_factory.make_tool_call("mcp__spy__echo", {"text": "hi"}),
        responses_factory.make_assistant_message("done"),
    ]
    client = FakeOpenAIModel(seq)

    injected_result = mcp_types.CallToolResult(
        content=[],
        isError=False,
        structuredContent={"ok": True, "injected": "yes"},
    )

    async with McpManager({}) as mcp:
        for name, slot in specs.items():
            await mcp.attach_server(name, slot)
        rec = RecordingHandler()
        inj = InjectHandler(result=injected_result)

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,
            handlers=[inj, rec],
        )

        await agent.run("say hi")

    # Underlying tool must NOT have been called
    assert counter == []

    # Verify the handler saw a function_call_output with our injected payload
    assert_function_call_output_structured(rec.records, ok=True, injected="yes")


@pytest.mark.asyncio
async def test_before_tool_call_abort_turn_synthesizes_denied_and_aborted_outputs(
    fake_openai_client_factory,
    responses_factory,
    make_spy_spec,
) -> None:
    counter: list[str] = []
    specs = make_spy_spec(counter)

    seq = [
        responses_factory.make_tool_call("mcp__spy__echo", {"text": "hi"}),
        responses_factory.make_assistant_message("done"),
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager({}) as mcp:
        for name, slot in specs.items():
            await mcp.attach_server(name, slot)
        rec = RecordingHandler()
        abort = AbortHandler()

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,
            handlers=[abort, rec],
        )

        await agent.run("say hi")

    # Should have emitted a function_call_output indicating denial
    assert_function_call_output_structured(rec.records, ok=False, error="test-deny")

    # Underlying tool should not have been called
    assert counter == []
