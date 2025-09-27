from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.openai_utils.model import (
    FakeOpenAIModel,
    ResponsesResult,
    Usage,
    ReasoningOut,
    FunctionCallOut,
    AssistantResponseMessage,
    ReasoningItem,
)


def _usage(inp: int = 0, out: int = 0) -> Usage:
    return Usage(input_tokens=inp, output_tokens=out, total_tokens=inp + out)


def _make_echo_server() -> FastMCP:
    mcp = FastMCP("echo")

    @mcp.tool()
    def echo(text: str) -> dict[str, Any]:
        return {"ok": True, "echo": text}

    return mcp


@pytest.mark.asyncio
async def test_reasoning_threading_filters_reasoning_from_next_input(
    reasoning_model: str,
    responses_factory,
) -> None:
    spec = make_inproc_slot_spec(_make_echo_server())

    # Sequence: model reasons then calls a tool, then returns a final message
    seq = [
        ResponsesResult(
            id="r1",
            usage=_usage(0, 0),
            output=[
                ReasoningOut(id="rs1"),
                FunctionCallOut(
                    call_id="call-1",
                    name="mcp__echo__echo",
                    arguments=json.dumps({"text": "hi"}),
                ),
            ],
        ),
        ResponsesResult(
            id="r2",
            usage=_usage(0, 1),
            output=[AssistantResponseMessage(text="ok")],
        ),
    ]
    client = FakeOpenAIModel(seq)
    # For live tests that exercise real models, prefer a reasoning-capable model via env override
    # (tests here use Fake client so this is only a hint for live variants)

    async with McpManager({"echo": spec}) as mcp:
        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,  # type: ignore[arg-type]
            handlers=[AutoHandler()],
        )

        res = await agent.run("say hi")

    # Assertions: the second Responses.create SHOULD include the prior reasoning item in the stateless full-input
    assert res.text.strip() == "ok"
    assert client.calls == 2
    # Capture the input sent on the second call (Pydantic InputItems)
    input_items = list(client.captured[1].input or [])
    # Expect at least one ReasoningItem forwarded from the prior response
    assert any(isinstance(it, ReasoningItem) for it in input_items), (
        f"Expected ReasoningItem forwarded in next-turn input: {input_items}"
    )
