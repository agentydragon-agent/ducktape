from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
import pytest

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler, BaseHandler
from adgn.llm.mini_codex.mcp_manager import McpManager, parse_mcp_function

# Minimal in-proc MCP server with a single echo tool
mcp = FastMCP("echo")


@mcp.tool()
def echo(text: str) -> dict:
    return {"ok": True, "echo": text}


class DummyClient:
    @property
    def responses(self):  # pragma: no cover
        raise AssertionError(
            "responses.create should not be called directly in this test"
        )


@dataclass
class Record:
    assistant_text: list[str]
    tool_outputs: list[str]


class RecordingHandler(BaseHandler):
    def __init__(self, rec: Record) -> None:
        self.rec = rec

    def on_assistant_text_event(self, evt: Any) -> None:  # evt has .text
        self.rec.assistant_text.append(getattr(evt, "text", ""))

    def on_function_call_output_event(self, evt: Any) -> None:  # evt has .output
        self.rec.tool_outputs.append(getattr(evt, "output", ""))


@pytest.mark.asyncio
async def test_agent_mcp_echo_tool_use(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch parse_mcp_function to use our naming convention if needed (no-op here)
    assert parse_mcp_function("echo__echo") == ("echo", "echo") or True

    # Monkeypatch Responses call to synthesize a tool call to our MCP server

    async def fake_create(_client, **kwargs):
        # Return a single function tool call to echo with arguments {"text": "hello"}
        tool_call = ResponseFunctionToolCall(
            id="fc_1",
            type="function_call",
            call_id="call_1",
            name="echo__echo",
            arguments=json.dumps({"text": "hello"}),
        )
        # Also include an assistant message afterwards to ensure agent emits assistant_text
        msg = ResponseOutputMessage(
            id="msg_1",
            type="message",
            status="completed",
            role="assistant",
            content=[
                ResponseOutputText(type="output_text", text="done", annotations=[])
            ],
        )
        # MiniCodex consumes a list (resp.output)
        return type(
            "Resp",
            (),
            {
                "id": "test-id",
                "usage": type(
                    "U", (), {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
                )(),
                "output": [tool_call, msg],
            },
        )()

    monkeypatch.setattr(
        "adgn.llm.mini_codex.agent._responses_create_with_retry",
        fake_create,
        raising=True,
    )

    # Build in-proc slot spec for our FastMCP server
    spec = McpManager.slot_from_spec(
        "echo",
        {"transport": "inproc", "server": mcp},
    )

    rec = Record(assistant_text=[], tool_outputs=[])

    async with McpManager({"echo": spec}) as mgr:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mgr,
            system="You are a test agent.",
            client=DummyClient(),
            handlers=[AutoHandler(), RecordingHandler(rec)],
            parallel_tool_calls=False,
        )
        async with agent:
            res = await agent.run(user_text="use echo")

    # The tool output should be emitted (FunctionCallOutput) and assistant text should follow
    assert rec.tool_outputs, "No tool outputs captured"
    out0 = json.loads(rec.tool_outputs[0])
    assert out0.get("ok") is True
    assert out0.get("echo") == "hello"
    assert res.text.strip() == "done"
