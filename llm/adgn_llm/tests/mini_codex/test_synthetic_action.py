from __future__ import annotations

import pytest
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.aggregating_handler import BaseHandler
from adgn_llm.mini_codex.loop_control import Abort, SyntheticAction
from adgn_llm.mini_codex.mcp_manager import McpManager


class SyntheticOnceHandler(BaseHandler):
    """Emits one SyntheticAction with precomputed SDK outputs, then stops."""

    def __init__(self, outputs) -> None:
        self._done = False
        self._outputs = list(outputs)

    def on_before_sample(self):  # type: ignore[override]
        if self._done:
            return Abort()
        self._done = True
        return SyntheticAction(outputs=self._outputs)


@pytest.mark.asyncio
async def test_mini_codex_handles_synthetic_action_without_api_calls(
    fake_openai_client_factory, assistant_response_factory, responses_factory
) -> None:
    client = fake_openai_client_factory([responses_factory.make_assistant_text_response(text="should_not_be_used")])
    async with McpManager({}) as mcp:
        resp = responses_factory.make_assistant_text_response(text="hello")
        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="You are a code agent.",
            client=client,
            handlers=[SyntheticOnceHandler(resp.output)],
        )
        res = await agent.run("hi")
        assert res.text.strip() == "hello"
        assert getattr(client.responses, "calls", 0) == 0
