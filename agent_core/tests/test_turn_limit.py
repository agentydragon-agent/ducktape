"""Tests for MaxTurnsHandler turn limiting."""

from __future__ import annotations

import pytest

from agent_core.agent import Agent
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import RequireAnyTool
from agent_core.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from agent_core_testing.responses import EchoMock
from openai_utils.model import OpenAIModelProto, UserMessage


@pytest.fixture
def make_agent_with_turn_limit(mcp_client_echo, recording_handler):
    """Factory for creating agents with turn limit."""

    async def _make(client: OpenAIModelProto, max_turns: int):
        return await Agent.create(
            mcp_client=mcp_client_echo,
            client=client,
            handlers=[FinishOnTextMessageHandler(), recording_handler, MaxTurnsHandler(max_turns=max_turns)],
            tool_policy=RequireAnyTool(),
        )

    return _make


async def test_turn_limit_exceeded(make_agent_with_turn_limit) -> None:
    """Test that MaxTurnsHandler raises MaxTurnsExceededError when limit is exceeded."""

    @EchoMock.mock()
    def mock(m: EchoMock):
        yield
        yield from m.echo_roundtrip("call1")
        yield from m.echo_roundtrip("call2")
        yield from m.echo_roundtrip("call3")
        yield from m.echo_roundtrip("call4")

    agent = await make_agent_with_turn_limit(mock, max_turns=3)
    agent.process_message(UserMessage.text("keep calling echo"))

    with pytest.raises(MaxTurnsExceededError) as exc_info:
        await agent.run()

    assert "exceeded maximum allowed turns (3)" in str(exc_info.value).lower()
    assert "stuck in a loop" in str(exc_info.value).lower()


async def test_turn_limit_within_bounds(make_agent_with_turn_limit) -> None:
    """Test that agent completes successfully when staying within turn limit."""

    @EchoMock.mock()
    def mock(m: EchoMock):
        yield
        yield from m.echo_roundtrip("call1")
        yield from m.echo_roundtrip("call2")
        yield m.assistant_text("done")

    agent = await make_agent_with_turn_limit(mock, max_turns=5)
    agent.process_message(UserMessage.text("call echo twice"))

    result = await agent.run()
    assert result.text.strip() == "done"


async def test_turn_limit_exactly_at_boundary(make_agent_with_turn_limit) -> None:
    """Test that agent can use exactly max_turns without error."""

    @EchoMock.mock()
    def mock(m: EchoMock):
        yield
        yield from m.echo_roundtrip("call1")
        yield from m.echo_roundtrip("call2")
        yield m.assistant_text("done")

    agent = await make_agent_with_turn_limit(mock, max_turns=3)
    agent.process_message(UserMessage.text("call echo twice"))

    result = await agent.run()
    assert result.text.strip() == "done"
