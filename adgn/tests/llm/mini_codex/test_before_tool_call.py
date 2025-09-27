from __future__ import annotations

import json
from typing import Any

from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.handler import (
    AbortTurnDecision,
    BypassToolInjectOutput,
    ToolCall,
)
from adgn.llm.mini_codex.loggers import RecordingHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.openai_utils.model import FakeOpenAIModel


def _make_spy_server(counter: list[str]) -> FastMCP:
    mcp = FastMCP("spy")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:
        counter.append(text)
        return {"ok": True, "echo": text}

    return mcp


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
    tool_call_response_factory,
    assistant_response_factory,
    responses_factory,
) -> None:
    counter: list[str] = []
    spec = make_inproc_slot_spec(_make_spy_server(counter))

    seq = [
        responses_factory.make_tool_call_response(
            call_id="call-1",
            name="mcp__spy__echo",
            arguments={"text": "hi"},
        ),
        responses_factory.make_assistant_text_response(text="done"),
    ]
    client = FakeOpenAIModel(seq)

    injected_result = mcp_types.CallToolResult(
        content=[],
        isError=False,
        structuredContent={"ok": True, "injected": "yes"},
    )

    async with McpManager({"spy": spec}) as mcp:
        rec = RecordingHandler()
        inj = InjectHandler(result=injected_result)

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[inj, rec],
        )

        await agent.run("say hi")

    # Underlying tool must NOT have been called
    assert counter == []

    # Verify the handler saw a function_call_output with our injected payload
    fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
    assert fcos, f"no function_call_output event found: {rec.records}"
    payload = (
        json.loads(fcos[-1]["output"])
        if isinstance(fcos[-1].get("output"), str)
        else fcos[-1]["output"]
    )
    assert payload.get("ok") is True
    assert payload.get("injected") == "yes"


@pytest.mark.asyncio
async def test_before_tool_call_abort_turn_synthesizes_denied_and_aborted_outputs(
    fake_openai_client_factory,
    tool_call_response_factory,
    assistant_response_factory,
    responses_factory,
) -> None:
    counter: list[str] = []
    spec = make_inproc_slot_spec(_make_spy_server(counter))

    seq = [
        tool_call_response_factory(
            "dummy-model",
            "call-1",
            "mcp__spy__echo",
            {"text": "hi"},
        ),
        assistant_response_factory("dummy-model", "done"),
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager({"spy": spec}) as mcp:
        rec = RecordingHandler()
        abort = AbortHandler()

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[abort, rec],
        )

        await agent.run("say hi")

    # Should have emitted a function_call_output indicating denial
    fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
    assert fcos, f"no function_call_output event found: {rec.records}"

    # The denied payload should be the last emitted (only call)
    payload = (
        json.loads(fcos[-1]["output"])
        if isinstance(fcos[-1].get("output"), str)
        else fcos[-1]["output"]
    )
    assert payload.get("ok") is False
    assert "User denied" in payload.get("error", "")

    # Underlying tool should not have been called
    assert counter == []
