from __future__ import annotations

import importlib.util
import json
import pathlib
from typing import Any

import pytest
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.aggregating_handler import AutoHandler
from adgn_llm.mini_codex.loggers import RecordingHandler
from adgn_llm.mini_codex.mcp_manager import McpManager
from mcp.server.fastmcp import FastMCP

_sdk_spec = importlib.util.spec_from_file_location("sdk_mocks", str(pathlib.Path(__file__).parent / "sdk_mocks.py"))
_sdk_mod = importlib.util.module_from_spec(_sdk_spec)
_sdk_spec.loader.exec_module(_sdk_mod)
FakeOpenAIClient = _sdk_mod.FakeOpenAIClient
make_tool_call_response = _sdk_mod.make_tool_call_response
make_assistant_text_response = _sdk_mod.make_assistant_text_response


def _make_echo_server() -> FastMCP:
    mcp = FastMCP("echo")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:  # noqa: ARG001
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
        responses_factory.make_tool_call_response(call_id="call-1", name="mcp__echo__echo", arguments={"text": "hi"}),
        responses_factory.make_assistant_text_response(text="done"),
    ]
    client = responses_factory.make_fake_client(seq)
    # Sanity: ensure test is using the fake client and not a real AsyncOpenAI
    assert type(client).__name__ == "FakeOpenAIClient", "test must use FakeOpenAIClient to avoid real network calls"

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
    payload = json.loads(fcos[-1]["output"]) if isinstance(fcos[-1].get("output"), str) else fcos[-1]["output"]
    assert isinstance(payload, dict)
    # Our echo server returns {ok: True, echo: "hi"}
    assert payload.get("ok") is True
    assert payload.get("echo") == "hi"
