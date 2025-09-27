from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.loggers import RecordingHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.openai_utils.model import (
    FakeOpenAIModel,
    ResponsesResult,
    Usage,
    FunctionCallOut,
    AssistantResponseMessage,
)


def _make_echo_server() -> FastMCP:
    mcp = FastMCP("echo")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:
        return {"ok": True, "echo": text}

    return mcp


@pytest.mark.asyncio
async def test_minicodex_with_sdk_mocks_executes_tool_and_returns_text(
    responses_factory,
) -> None:
    # Build in-proc FastMCP server spec named 'echo'
    spec = make_inproc_slot_spec(_make_echo_server())

    # Responses sequence:
    # 1) Model asks to call mcp__echo__echo with {"text": "hi"}
    # 2) Model returns a final assistant message "done"
    seq = [
        ResponsesResult(
            id="fc",
            usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0),
            output=[
                FunctionCallOut(
                    call_id="call_1",
                    name="mcp__echo__echo",
                    arguments=json.dumps({"text": "hi"}),
                )
            ],
        ),
        ResponsesResult(
            id="msg",
            usage=Usage(input_tokens=0, output_tokens=1, total_tokens=1),
            output=[AssistantResponseMessage(text="done")],
        ),
    ]
    client = FakeOpenAIModel(seq)

    async with McpManager({"echo": spec}) as mcp:
        # Minimal handler stack: use a RecordingHandler to capture function_call_output events

        rec = RecordingHandler()

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[AutoHandler(), rec],
        )

        res = await agent.run("say hi")

    # Verify final text returned
    assert res.text.strip() == "done"
    # Verify the handler saw a function_call_output
    fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
    assert fcos, f"no function_call_output event found: {rec.records}"
    payload = (
        json.loads(fcos[-1]["output"])
        if isinstance(fcos[-1].get("output"), str)
        else fcos[-1]["output"]
    )
    assert isinstance(payload, dict)
    # Our echo server returns {ok: True, echo: "hi"}
    assert payload.get("ok") is True
    assert payload.get("echo") == "hi"
