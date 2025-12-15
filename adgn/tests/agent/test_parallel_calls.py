import time
from typing import Any

from hamcrest import assert_that, greater_than_or_equal_to, has_length
from pydantic import BaseModel

from adgn.agent.agent import Agent
from adgn.agent.events import ToolCall, ToolCallOutput
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Abort, InjectItems, RequireAnyTool
from adgn.openai_utils.builders import ItemFactory
from adgn.openai_utils.model import UserMessage
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


async def test_parallel_tool_calls_reduce_wall_time(compositor, compositor_client, slow_server, recording_handler):
    # Two tool calls with ~0.30s latency each; if run in parallel, wall time ~0.30-0.45s
    # Mount slow server and capture Mounted object
    mounted_slow = await compositor.mount_inproc("dummy", slow_server)

    factory = ItemFactory(call_id_prefix="test")
    tc1 = factory.mcp_tool_call(mounted_slow.prefix, "slow", SlowInput())
    tc2 = factory.mcp_tool_call(mounted_slow.prefix, "slow2", Slow2Input())

    handler = OneShotSyntheticHandler(outputs=[tc1, tc2])

    agent = await Agent.create(
        mcp_client=compositor_client,
        client=NoopOpenAIClient(),  # SyntheticAction path bypasses OpenAI
        parallel_tool_calls=True,
        handlers=[handler, recording_handler],
        tool_policy=RequireAnyTool(),
    )
    agent.insert_message(UserMessage.text("go"))

    t0 = time.perf_counter()
    await agent.run()
    elapsed = time.perf_counter() - t0

    # Assert shorter than serial (~0.60s), with generous headroom for CI noise
    # Threshold tuned for CI noise; serial takes ~0.60s, expect faster here
    assert elapsed < 0.55, f"expected parallel speedup; took {elapsed:.3f}s"

    # Sanity checks on outputs/metrics via recording handler
    tool_calls = [e for e in recording_handler.records if isinstance(e, ToolCall)]
    tool_outputs = [e for e in recording_handler.records if isinstance(e, ToolCallOutput)]
    assert_that(tool_calls, has_length(greater_than_or_equal_to(2)))
    assert_that(tool_outputs, has_length(greater_than_or_equal_to(2)))
