from __future__ import annotations

import pytest

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.loggers import RecordingHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.openai_utils.model import FakeOpenAIModel, BoundOpenAIModel
from tests.llm.support.openai_mock import LIVE


@pytest.mark.parametrize(
    "client_mode",
    [
        pytest.param("mock", id="mock"),
        pytest.param(LIVE, id="live", marks=pytest.mark.live_llm),
    ],
)
@pytest.mark.asyncio
async def test_minicodex_with_sdk_mocks_executes_tool_and_returns_text(
    responses_factory,
    live_openai,
    client_mode,
    make_echo_spec,
) -> None:
    # Build in-proc FastMCP server spec named 'echo'
    specs = make_echo_spec()

    # Responses sequence:
    # 1) Model asks to call mcp__echo__echo with {"text": "hi"}
    # 2) Model returns a final assistant message "done"
    if client_mode is not LIVE:
        client = FakeOpenAIModel(
            [
                responses_factory.make_tool_call("mcp__echo__echo", {"text": "hi"}),
                responses_factory.make_assistant_message("done"),
            ]
        )
    else:
        client = BoundOpenAIModel(client=live_openai, model=responses_factory.model)

    async with McpManager(specs) as mcp:
        # Minimal handler stack: use a RecordingHandler to capture function_call_output events

        rec = RecordingHandler()

        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,
            handlers=[AutoHandler(), rec],
        )

        res = await agent.run("say hi")

    # Verify final text returned
    assert res.text.strip() == "done"
    # Verify the handler saw a function_call_output
    fcos = [e for e in rec.records if e.get("kind") == "function_call_output"]
    assert fcos, f"no function_call_output event found: {rec.records}"
    payload = fcos[-1].get("result") or {}
    structured = payload.get("structuredContent") or {}
    assert structured == {"ok": True, "echo": "hi"}
