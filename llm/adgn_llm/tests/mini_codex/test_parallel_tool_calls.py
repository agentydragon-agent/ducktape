import asyncio
import json
import time
from typing import Any

import pytest
from mcp import types as mcp_types
from openai.types.responses import ResponseFunctionToolCall

from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.loop_control import Abort, SyntheticAction
from adgn_llm.mini_codex.aggregating_handler import BaseHandler


class OneShotSyntheticHandler(BaseHandler):
    """Handler that returns a SyntheticAction once, then Abort."""

    def __init__(self, outputs: list[Any]):
        self._done = False
        self._outputs = outputs

    def on_before_sample(self):  # returns SyntheticAction first, then Abort
        if not self._done:
            self._done = True
            return SyntheticAction(outputs=self._outputs)
        return Abort()

    # No-ops for hooks used by agent
    def on_reasoning(self, *_a, **_k):  # pragma: no cover - not used here
        return None

    def on_assistant_text(self, *_a, **_k):  # pragma: no cover - not used here
        return None

    def on_tool_call(self, *_a, **_k):  # pragma: no cover - not used here
        return None

    def on_function_call_output(self, *_a, **_k):  # pragma: no cover - not used here
        return None


class DummySession:
    def __init__(self, per_call_secs: float = 0.30) -> None:
        self._per_call_secs = per_call_secs

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None):
        # Simulate IO latency per tool
        await asyncio.sleep(self._per_call_secs)
        payload = {"ok": True, "tool": name, "args": arguments or {}}
        # Return an MCP CallToolResult that the agent knows how to serialize
        return mcp_types.CallToolResult(
            content=[
                mcp_types.TextContent(
                    type="text",
                    text=json.dumps(payload, ensure_ascii=False),
                )
            ],
            isError=False,
        )


class DummyMcp:
    server_names = ["dummy"]

    async def list_resources(self, only: list[str] | None = None):
        return []

    async def list_tools(self):
        # Advertise two namespaced MCP tools
        return [
            {
                "type": "function",
                "name": "mcp__dummy__slow",
                "description": "slow tool",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
            },
            {
                "type": "function",
                "name": "mcp__dummy__slow2",
                "description": "slow tool 2",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
            },
        ]

    async def get_server_initialize(self, _sname: str):
        class Init:
            instructions = "dummy"

        return Init()

    def resolve_function(self, fullname: str) -> tuple[str, str]:
        # mcp__{server}__{tool}
        parts = fullname.split("__", 2)
        server = parts[1]
        tool = parts[2]
        return server, tool

    async def get_session(self, _server: str):
        return DummySession()

    async def read_resource(self, *_a, **_k):  # pragma: no cover - not used here
        raise NotImplementedError


@pytest.mark.asyncio
async def test_parallel_tool_calls_reduce_wall_time():
    mcp = DummyMcp()
    # Two tool calls with ~0.30s latency each; if run in parallel, wall time ~0.30–0.45s
    tc1 = ResponseFunctionToolCall(type="function_call", name="mcp__dummy__slow", arguments="{}", call_id="c1")
    tc2 = ResponseFunctionToolCall(type="function_call", name="mcp__dummy__slow2", arguments="{}", call_id="c2")

    handler = OneShotSyntheticHandler(outputs=[tc1, tc2])

    # Create agent with the controller wrapped as a handler so loop control comes from handlers
    agent = MiniCodex(
        model="noop",
        system="test",
        mcp=mcp,
        client=None,  # SyntheticAction path bypasses OpenAI
        parallel_tool_calls=True,
        handlers=[handler],
    )

    t0 = time.perf_counter()
    res = await agent.run("go")
    elapsed = time.perf_counter() - t0

    # Assert shorter than serial (~0.60s), with generous headroom for CI noise
    assert elapsed < 0.55, f"expected parallel speedup; took {elapsed:.3f}s"

    # Sanity checks on outputs/metrics
    assert res.metrics.tool_calls == 2
    kinds = [evt.get("kind") for evt in res.sequence if isinstance(evt, dict)]
    # Expect two tool_call and two function_call_output events at minimum
    assert kinds.count("tool_call") >= 2
    assert kinds.count("function_call_output") >= 2
