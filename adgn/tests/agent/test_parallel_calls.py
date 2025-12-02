import time
from typing import Any

from pydantic import BaseModel

from adgn.agent.agent import MiniCodex
from adgn.agent.loop_control import Abort, InjectItems, RequireAnyTool
from adgn.agent.reducer import BaseHandler
from adgn.openai_utils.builders import ItemFactory
from tests.agent.helpers import NoopOpenAIClient


class SlowInput(BaseModel):
    """Empty input for slow() tool."""


class Slow2Input(BaseModel):
    """Empty input for slow2() tool."""


class OneShotSyntheticHandler(BaseHandler):
    """Handler that injects synthetic output once, then aborts."""

    def __init__(self, outputs: list[Any]):
        self._done = False
        self._outputs = outputs

    def on_before_sample(self):
        if not self._done:
            self._done = True
            return InjectItems(items=tuple(self._outputs))
        return Abort()


async def test_parallel_tool_calls_reduce_wall_time(make_compositor, slow_server, recording_handler):
    # Two tool calls with ~0.30s latency each; if run in parallel, wall time ~0.30-0.45s
    factory = ItemFactory(call_id_prefix="test")
    tc1 = factory.mcp_tool_call("dummy", "slow", SlowInput())
    tc2 = factory.mcp_tool_call("dummy", "slow2", Slow2Input())

    handler = OneShotSyntheticHandler(outputs=[tc1, tc2])

    async with make_compositor({"dummy": slow_server}) as (mcp_client, _):
        agent = await MiniCodex.create(
            system="test",
            mcp_client=mcp_client,
            client=NoopOpenAIClient(),  # SyntheticAction path bypasses OpenAI
            parallel_tool_calls=True,
            handlers=[handler, recording_handler],
            tool_policy=RequireAnyTool(),
        )

        t0 = time.perf_counter()
        await agent.run("go")
        elapsed = time.perf_counter() - t0

    # Assert shorter than serial (~0.60s), with generous headroom for CI noise
    # Threshold tuned for CI noise; serial takes ~0.60s, expect faster here
    assert elapsed < 0.55, f"expected parallel speedup; took {elapsed:.3f}s"

    # Sanity checks on outputs/metrics via recording handler
    tc_count = len([e for e in recording_handler.records if e.get("kind") == "tool_call"])
    function_call_output_count = len([e for e in recording_handler.records if e.get("kind") == "function_call_output"])
    assert tc_count >= 2
    assert function_call_output_count >= 2
    kinds = [evt.get("kind") for evt in recording_handler.records if isinstance(evt, dict)]
    assert kinds.count("tool_call") >= 2
    assert kinds.count("function_call_output") >= 2
