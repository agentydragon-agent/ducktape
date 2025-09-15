import asyncio
import time
from typing import Any

import pytest

from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.loop_control import Abort, SyntheticAction
from adgn_llm.mini_codex.aggregating_handler import BaseHandler
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from mcp.server.fastmcp import FastMCP
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mcp.helpers import make_response_function_tool_call_full


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


def _make_slow_server(per_call_secs: float = 0.30) -> FastMCP:
    """Return a FastMCP server implementing two slow tools.

    The tools are async and sleep for per_call_secs to simulate latency. This
    exercises the real inproc FastMCP transport in tests (higher fidelity).
    """
    mcp = FastMCP("dummy")

    @mcp.tool()
    async def slow(**kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(per_call_secs)
        return {"ok": True, "tool": "slow", "args": kwargs}

    @mcp.tool()
    async def slow2(**kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(per_call_secs)
        return {"ok": True, "tool": "slow2", "args": kwargs}

    return mcp


@pytest.mark.asyncio
async def test_parallel_tool_calls_reduce_wall_time():
    # Build a real inproc FastMCP server with two slow tools
    spec = make_inproc_slot_spec(_make_slow_server())

    # Two tool calls with ~0.30s latency each; if run in parallel, wall time ~0.30–0.45s
    tc1 = make_response_function_tool_call_full("dummy", "slow", {}, as_json=True)
    tc2 = make_response_function_tool_call_full("dummy", "slow2", {}, as_json=True)

    handler = OneShotSyntheticHandler(outputs=[tc1, tc2])

    from adgn_llm.mini_codex.loggers import RecordingHandler

    rec = RecordingHandler()

    # Use McpManager context to wire the inproc slot into a manager the agent expects
    async with McpManager({"dummy": spec}) as mcp:
        # Create agent with the controller wrapped as a handler so loop control comes from handlers
        agent = MiniCodex(
            model="noop",
            system="test",
            mcp=mcp,
            client=None,  # SyntheticAction path bypasses OpenAI
            parallel_tool_calls=True,
            handlers=[handler, rec],
        )

        t0 = time.perf_counter()
        await agent.run("go")

        # Wait for recording handler to observe expected events (tool_call + function_call_output)
        # This synchronizes with FastMCP background work before closing McpManager to avoid anyio
        # cancel-scope teardown races.
        async def _wait_for_records(timeout: float = 2.0) -> None:
            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                if len(rec.records) >= 4:
                    return
                await asyncio.sleep(0.02)
            # fall through; let assertions fail later

        await _wait_for_records(timeout=2.0)
        elapsed = time.perf_counter() - t0

    # Assert shorter than serial (~0.60s), with generous headroom for CI noise
    assert elapsed < 0.55, f"expected parallel speedup; took {elapsed:.3f}s"

    # Sanity checks on outputs/metrics via recording handler
    tc_count = len([e for e in rec.records if e.get("kind") == "tool_call"])
    fco_count = len([e for e in rec.records if e.get("kind") == "function_call_output"])
    assert tc_count >= 2
    assert fco_count >= 2
    kinds = [evt.get("kind") for evt in rec.records if isinstance(evt, dict)]
    assert kinds.count("tool_call") >= 2
    assert kinds.count("function_call_output") >= 2
