from __future__ import annotations

import pytest

from mcp import types as mcp_types

from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import AutoHandler
from adgn.agent.handler import (
    AbortTurnDecision,
    BypassToolInjectOutput,
    ToolCall,
)
from adgn.agent.loggers import RecordingHandler
from adgn.agent.mcp_manager import McpManager
from adgn.openai_utils.model import FakeOpenAIModel


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

    async with McpManager(specs) as mcp:
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
    fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
    assert fcos, f"no function_call_output event found: {rec.records}"
    payload = fcos[-1].get("result") or {}
    structured = payload.get("structuredContent") or {}
    assert structured == {"ok": True, "injected": "yes"}


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

    async with McpManager(specs) as mcp:
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
    fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
    assert fcos, f"no function_call_output event found: {rec.records}"

    # The denied payload should be the last emitted (only call)
    payload = fcos[-1].get("result") or {}
    structured = payload.get("structuredContent") or {}
    assert structured == {"ok": False, "error": "test-deny"}

    # Underlying tool should not have been called
    assert counter == []
