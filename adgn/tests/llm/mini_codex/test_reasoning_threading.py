from __future__ import annotations

import pytest
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.openai_utils.model import (
    FakeOpenAIModel,
    ReasoningItem,
)


@pytest.mark.asyncio
async def test_reasoning_threading_filters_reasoning_from_next_input(
    reasoning_model: str,
    responses_factory,
    make_echo_spec,
) -> None:
    specs = make_echo_spec()

    # Sequence: model reasons then calls a tool, then returns a final message
    seq = [
        responses_factory.make(
            responses_factory.make_item_reasoning(),
            responses_factory.tool_call("mcp__echo__echo", {"text": "hi"}),
        ),
        responses_factory.make_assistant_message("ok"),
    ]
    client = FakeOpenAIModel(seq)
    # For live tests that exercise real models, prefer a reasoning-capable model via env override
    # (tests here use Fake client so this is only a hint for live variants)

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=responses_factory.model,
            mcp=mcp,
            system="test",
            client=client,
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
