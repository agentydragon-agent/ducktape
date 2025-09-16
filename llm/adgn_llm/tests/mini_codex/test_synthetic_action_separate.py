from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib
from typing import Any

import pytest
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.aggregating_handler import AutoHandler
from adgn_llm.mini_codex.handler import (
    BypassToolInjectOutput,
    ContinueDecision,
    ToolCall,
)
from adgn_llm.mini_codex.loggers import RecordingHandler
from adgn_llm.mini_codex.loop_control import Auto, Continue
from adgn_llm.mini_codex.loop_control import SyntheticAction as LC_SyntheticAction
from adgn_llm.mini_codex.mcp_manager import McpManager
from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from openai.types.responses import ResponseFunctionToolCall

_sdk_spec = importlib.util.spec_from_file_location("sdk_mocks", str(pathlib.Path(__file__).parent / "sdk_mocks.py"))
_sdk_mod = importlib.util.module_from_spec(_sdk_spec)
_sdk_spec.loader.exec_module(_sdk_mod)
FakeOpenAIClient = _sdk_mod.FakeOpenAIClient
make_assistant_text_response = _sdk_mod.make_assistant_text_response


def _make_spy_server(counter: list[str]) -> FastMCP:
    mcp = FastMCP("spy")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:  # noqa: ARG001
        counter.append(text)
        return {"ok": True, "echo": text}

    @mcp.tool(name="tool1")
    def tool1(old_text: str, new_text: str) -> dict[str, Any]:  # noqa: ARG001
        counter.append(f"tool1:{old_text}->{new_text}")
        return {"ok": True, "replaced": True}

    @mcp.tool(name="tool2")
    def tool2() -> dict[str, Any]:  # noqa: ARG001
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
        fc = ResponseFunctionToolCall(
            arguments=json.dumps({"old_text": "HELLO_WORLD", "new_text": "GOODBYE_WORLD"}),
            call_id="client:replace-1",
            name="mcp__spy__tool1",
            type="function_call",
        )
        return LC_SyntheticAction(outputs=[fc])


class BypassInjector(AutoHandler):
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
async def test_synthetic_action_executes_tool_via_mcp():
    """SyntheticAction should cause the agent to execute the tool through MCP."""
    counter: list[str] = []
    spec = make_inproc_slot_spec(_make_spy_server(counter))

    seq = [make_assistant_text_response(model="dummy-model", text="done")]
    client = FakeOpenAIClient(seq)

    async with McpManager({"spy": spec}) as mcp:
        rec = RecordingHandler()
        inv = SyntheticInvoker()

        agent = await MiniCodex.create(
            model="dummy-model",
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[inv, rec],
            parallel_tool_calls=False,
        )

        # Bound the run with an explicit timeout to avoid hangs
        await asyncio.wait_for(agent.run("execute"), timeout=30)

        # The inproc spy tool should have been called once for tool1
        assert any(item.startswith("tool1:") for item in counter), f"tool not invoked: {counter}"


@pytest.mark.asyncio
async def test_bypass_inject_preempts_mcp_call():
    """BypassToolInjectOutput should preempt MCP execution and prevent the tool call."""
    counter: list[str] = []
    spec = make_inproc_slot_spec(_make_spy_server(counter))

    seq = [make_assistant_text_response(model="dummy-model", text="done")]
    client = FakeOpenAIClient(seq)

    injected_result = mcp_types.CallToolResult(
        content=[], isError=False, structuredContent={"ok": True, "injected": "yes"}
    )

    async with McpManager({"spy": spec}) as mcp:
        rec = RecordingHandler()
        inv = SyntheticInvoker()
        inj = BypassInjector(result=injected_result)

        agent = await MiniCodex.create(
            model="dummy-model",
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[inv, inj, rec],
            parallel_tool_calls=False,
        )

        await asyncio.wait_for(agent.run("execute"), timeout=30)

        # Verify injected function_call_output was emitted
        fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
        assert fcos, f"no function_call_output event found: {rec.records}"
        payload = json.loads(fcos[-1]["output"]) if isinstance(fcos[-1].get("output"), str) else fcos[-1]["output"]
        assert payload.get("ok") is True
        assert payload.get("injected") == "yes"

        # Assert no MCP tool invocation occurred
        assert not any(item.startswith("tool1:") for item in counter), f"MCP tool was called despite bypass: {counter}"
