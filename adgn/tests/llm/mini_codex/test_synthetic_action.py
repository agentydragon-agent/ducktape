from __future__ import annotations

import pytest

from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import BaseHandler
from adgn.llm.mini_codex.loop_control import Abort, Continue, Auto
from adgn.llm.mini_codex.mcp_manager import McpManager


class SyntheticOnceHandler(BaseHandler):
    """Emits one SyntheticAction with precomputed SDK outputs, then stops."""

    def __init__(self, outputs) -> None:
        self._done = False
        self._outputs = list(outputs)

    def on_before_sample(self):  # type: ignore[override]
        if self._done:
            return Abort()
        self._done = True
        return Continue(Auto(), inserts_input=tuple(self._outputs), skip_sampling=True)


@pytest.mark.asyncio
async def test_mini_codex_handles_synthetic_action_without_api_calls(
    fake_openai_client_factory,
    responses_factory,
) -> None:
    client = fake_openai_client_factory(
        [responses_factory.make_assistant_message("should_not_be_used")],
    )
    async with McpManager({}) as mcp:
        resp = responses_factory.make_assistant_message("hello")
        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="You are a code agent.",
            client=client,
            handlers=[SyntheticOnceHandler(resp.output)],
        )
        res = await agent.run("hi")
        assert res.text.strip() == "hello"
        # MiniCodex uses the protocol method `.responses_create` — ensure we made no API calls.
        assert getattr(client, "calls", 0) == 0
