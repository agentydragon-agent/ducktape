from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from openai.types.responses import ResponseFunctionToolCall
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.handler import (
    BypassToolInjectOutput,
    ContinueDecision,
    ToolCall,
)
from adgn.llm.mini_codex.loggers import RecordingHandler
from adgn.llm.mini_codex.loop_control import (
    Abort,
    Auto,
    Continue,
)
from adgn.llm.mini_codex.mcp_manager import McpManager


def _make_spy_server(counter: list[str]) -> FastMCP:
    mcp = FastMCP("spy")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:
        counter.append(text)
        return {"ok": True, "echo": text}

    # Also provide a tiny editor tool on the same inproc server for tests so
    # we don't need a separate 'editor' slot.
    @mcp.tool(name="tool1")
    def tool1(old_text: str, new_text: str) -> dict[str, Any]:
        return {"ok": True, "replaced": True}

    @mcp.tool(name="tool2")
    def tool2() -> dict[str, Any]:
        return {"ok": True}

    return mcp


class LocalInjectHandler(AutoHandler):
    def __init__(self, result: mcp_types.CallToolResult):
        super().__init__()
        self._result = result
        self._fired = False

    def on_before_sample(self):
        # Produce a synthetic function_call output for this sampling step once
        if not self._fired:
            self._fired = True
            fc = ResponseFunctionToolCall(
                arguments=json.dumps(
                    {"old_text": "HELLO_WORLD", "new_text": "GOODBYE_WORLD"},
                ),
                call_id="client:replace-1",
                name="mcp__spy__tool1",
                type="function_call",
            )
            return Continue(Auto(), inserts_input=(fc,), skip_sampling=True)
        # After firing once, abort the turn to avoid infinite loops in tests
        return Abort()

    async def before_tool_call(self, evt: ToolCall) -> BypassToolInjectOutput:
        # Intercept the synthetic tool1 call by name
        if "tool1" in evt.name:
            return BypassToolInjectOutput(result=self._result)
        # Default: continue

        return ContinueDecision()


@pytest.mark.parametrize("mode", ["mock", "live"])
@pytest.mark.asyncio
async def test_synthetic_function_call_local_tool(mode: str, responses_factory) -> None:
    # Mock mode uses FakeOpenAIClient and an inproc MCP; live mode is a placeholder
    counter: list[str] = []
    spec = make_inproc_slot_spec(_make_spy_server(counter))

    # Minimal sequence: no actual function_call from model (we use SyntheticAction)
    seq = [responses_factory.make_assistant_text_response(text="done")]
    client = responses_factory.make_fake_client(seq)

    injected_result = mcp_types.CallToolResult(
        content=[],
        isError=False,
        structuredContent={"ok": True, "injected": "yes"},
    )

    async with McpManager({"spy": spec}) as mcp:
        rec = RecordingHandler()
        inj = LocalInjectHandler(result=injected_result)

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[inj, rec],
            parallel_tool_calls=False,
        )

        # Run the agent; SyntheticAction should be processed entirely in-process
        # Bound the run with an explicit timeout to avoid long-lived hangs in CI
        await asyncio.wait_for(agent.run("execute"), timeout=30)

        # Verify the recorded handler captured a function_call_output with our injected payload
        fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
        assert fcos, f"no function_call_output event found: {rec.records}"
        payload = (
            json.loads(fcos[-1]["output"])
            if isinstance(fcos[-1].get("output"), str)
            else fcos[-1]["output"]
        )
        assert payload.get("ok") is True
        assert payload.get("injected") == "yes"

        # Underlying tool (mcp) must NOT have been called because we injected local result
        assert counter == []
