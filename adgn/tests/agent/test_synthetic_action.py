from __future__ import annotations

from adgn.agent.agent import MiniCodex
from adgn.agent.loop_control import Abort, Auto, Continue
from adgn.agent.reducer import BaseHandler


class SyntheticOnceHandler(BaseHandler):
    """Emits one SyntheticAction with precomputed SDK outputs, then stops."""

    def __init__(self, outputs) -> None:
        self._done = False
        self._outputs = list(outputs)

    def on_before_sample(self):
        if self._done:
            return Abort()
        self._done = True
        return Continue(Auto(), inserts_input=tuple(self._outputs), skip_sampling=True)


async def test_mini_codex_handles_synthetic_action_without_api_calls(
    make_fake_openai, responses_factory, pg_session_policy_only
) -> None:
    client = make_fake_openai([responses_factory.make_assistant_message("should_not_be_used")])
    resp = responses_factory.make_assistant_message("hello")
    agent = await MiniCodex.create(
        mcp_client=pg_session_policy_only,
        system="You are a code agent.",
        client=client,
        handlers=[SyntheticOnceHandler(resp.output)],
    )
    res = await agent.run("hi")
    assert res.text.strip() == "hello"
    # MiniCodex uses the protocol method `.responses_create` — ensure we made no API calls.
    assert getattr(client, "calls", 0) == 0
