from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

# OpenAI Responses SDK types
from openai.types.responses import Response
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)
import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.mcp_manager import McpManager


def _usage(inp: int = 0, out: int = 0) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=inp,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens=out,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=inp + out,
    )


class _CapturingResponses:
    def __init__(self, seq: list[Response]) -> None:
        self._seq = seq
        self.calls = 0
        self.captured: list[dict[str, Any]] = []

    async def create(
        self,
        **kwargs: Any,
    ) -> Response:  # OpenAI AsyncResponses-compatible
        self.captured.append(dict(kwargs))
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        return self._seq[idx]


class CapturingClient:
    def __init__(self, seq: list[Response]) -> None:
        self.responses = _CapturingResponses(seq)


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
        responses_factory.make_reasoning_then_tool(
            call_id="call-1",
            name="mcp__echo__echo",
            arguments={"text": "hi"},
        ),
        responses_factory.make_final_assistant("ok"),
    ]
    client = CapturingClient(seq)
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
    assert client.responses.calls == 2
    # Capture the input sent on the second call
    second = client.responses.captured[1]
    input_items = second.get("input") or []
    assert isinstance(input_items, list)
    # Expect at least one reasoning item forwarded from the prior response
    assert any(
        isinstance(it, dict) and it.get("type") == "reasoning" for it in input_items
    ), (
        f"Expected reasoning item to be forwarded in next-turn input: {json.dumps(input_items, ensure_ascii=False)}"
    )
