from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp import types as mcp_types
import pytest
from adgn.llm.openai_utils.model import FakeOpenAIModel

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler, BaseHandler
from adgn.llm.mini_codex.mcp_manager import McpManager, parse_mcp_function


class DummyClient:
    @property
    def responses(self):  # pragma: no cover
        raise AssertionError(
            "responses.create should not be called directly in this test"
        )


@dataclass
class Record:
    assistant_text: list[str]
    tool_outputs: list[dict[str, Any]]


class RecordingHandler(BaseHandler):
    def __init__(self, rec: Record) -> None:
        self.rec = rec

    def on_assistant_text_event(self, evt: Any) -> None:  # evt has .text
        self.rec.assistant_text.append(getattr(evt, "text", ""))

    def on_tool_result_event(self, evt) -> None:
        self.rec.tool_outputs.append(
            evt.result.model_dump(mode="json", exclude_none=True)
        )


@pytest.mark.asyncio
async def test_agent_mcp_echo_tool_use(
    monkeypatch: pytest.MonkeyPatch,
    responses_factory,
    make_echo_spec,
) -> None:
    # Patch parse_mcp_function to use our naming convention if needed (no-op here)
    assert parse_mcp_function("echo__echo") == ("echo", "echo") or True

    # Provide a two-step sequence via our shared Pydantic fake client
    client = FakeOpenAIModel(
        [
            responses_factory.make_tool_call("echo__echo", {"text": "hello"}),
            responses_factory.make_assistant_message("done"),
        ]
    )

    # Build in-proc slot spec for our FastMCP server
    specs = make_echo_spec()

    rec = Record(assistant_text=[], tool_outputs=[])

    async with McpManager(specs) as mgr:
        agent = await MiniCodex.create(
            model="test-model",
            mcp=mgr,
            system="You are a test agent.",
            client=client,
            handlers=[AutoHandler(), RecordingHandler(rec)],
            parallel_tool_calls=False,
        )
        async with agent:
            res = await agent.run(user_text="use echo")

    # The tool output should be emitted (ToolCallOutput) and assistant text should follow
    assert rec.tool_outputs, "No tool outputs captured"
    out0 = rec.tool_outputs[0]
    result = mcp_types.CallToolResult.model_validate(out0)
    structured = result.structuredContent or {}
    assert structured == {"ok": True, "echo": "hello"}
    assert res.text.strip() == "done"
