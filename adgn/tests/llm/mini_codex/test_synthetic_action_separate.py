from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from adgn.llm.openai_utils.model import (
    FunctionCallItem,
    FakeOpenAIModel,
)
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.handler import (
    BaseHandler,
    BypassToolInjectOutput,
    ContinueDecision,
    ToolCall,
)
from adgn.llm.mini_codex.loggers import RecordingHandler
from adgn.llm.mini_codex.loop_control import Auto, Continue
from adgn.llm.mini_codex.mcp_manager import McpManager


def _make_spy_server(counter: list[str]) -> FastMCP:
    mcp = FastMCP("spy")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:
        counter.append(text)
        return {"ok": True, "echo": text}

    @mcp.tool(name="tool1")
    def tool1(old_text: str, new_text: str) -> dict[str, Any]:
        counter.append(f"tool1:{old_text}->{new_text}")
        return {"ok": True, "replaced": True}

    @mcp.tool(name="tool2")
    def tool2() -> dict[str, Any]:
        counter.append("tool2")
        return {"ok": True}

    return mcp


class SyntheticInvoker(AutoHandler):
    """Handler that forces the agent to take a synthetic model action (function_call)

    The agent should process this SyntheticAction by executing the tool via MCP.
    """

    def __init__(self) -> None:
        super().__init__()
        self._fired = False

    def on_before_sample(self):
        if self._fired:
            return Continue(Auto())
        self._fired = True
        fc = FunctionCallItem(
            name="mcp__spy__tool1",
            call_id="client:replace-1",
            arguments=json.dumps(
                {"old_text": "HELLO_WORLD", "new_text": "GOODBYE_WORLD"}
            ),
        )
        return Continue(Auto(), inserts_input=(fc,), skip_sampling=True)


class BypassInjector(BaseHandler):
    """Handler that injects a local CallToolResult and bypasses MCP execution."""

    def __init__(self, result: mcp_types.CallToolResult):
        super().__init__()
        self._result = result

    async def before_tool_call(self, evt: ToolCall) -> BypassToolInjectOutput:
        # Intercept the tool1 call and return bypass injection
        if "tool1" in evt.name:
            return BypassToolInjectOutput(result=self._result)
        return ContinueDecision()


@pytest.mark.asyncio
async def test_synthetic_action_executes_tool_via_mcp(responses_factory):
    """SyntheticAction should cause the agent to execute the tool through MCP."""
    counter: list[str] = []
    spec = make_inproc_slot_spec(_make_spy_server(counter))

    seq = [responses_factory.make_assistant_message("done")]
    client = FakeOpenAIModel(seq)

    async with McpManager({"spy": spec}) as mcp:
        rec = RecordingHandler()
        inv = SyntheticInvoker()

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,
            handlers=[inv, rec],
            parallel_tool_calls=False,
        )

        # Bound the run with an explicit timeout to avoid hangs
        await asyncio.wait_for(agent.run("execute"), timeout=30)

        # The inproc spy tool should have been called once for tool1
        assert any(item.startswith("tool1:") for item in counter), (
            f"tool not invoked: {counter}"
        )


@pytest.mark.asyncio
async def test_bypass_inject_preempts_mcp_call(responses_factory):
    """BypassToolInjectOutput should preempt MCP execution and prevent the tool call."""
    counter: list[str] = []
    spec = make_inproc_slot_spec(_make_spy_server(counter))

    seq = [responses_factory.make_assistant_message("done")]
    client = FakeOpenAIModel(seq)

    injected_result = mcp_types.CallToolResult(
        content=[],
        isError=False,
        structuredContent={"ok": True, "injected": "yes"},
    )

    async with McpManager({"spy": spec}) as mcp:
        rec = RecordingHandler()
        inv = SyntheticInvoker()
        inj = BypassInjector(result=injected_result)

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,
            handlers=[inv, inj, rec],
            parallel_tool_calls=False,
        )

        await asyncio.wait_for(agent.run("execute"), timeout=30)

        # Verify injected function_call_output was emitted
        fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
        assert fcos, f"no function_call_output event found: {rec.records}"
        payload = fcos[-1].get("result") or {}
        structured = payload.get("structuredContent") or {}
        assert structured == {"ok": True, "injected": "yes"}

        # Assert no MCP tool invocation occurred
        assert not any(item.startswith("tool1:") for item in counter), (
            f"MCP tool was called despite bypass: {counter}"
        )
