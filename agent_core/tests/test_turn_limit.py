"""Tests for MaxTurnsHandler turn limiting."""

from __future__ import annotations

import pytest

from agent_core.agent import Agent
from agent_core.handler import FinishOnTextMessageHandler
from agent_core.loop_control import RequireAnyTool
from agent_core.testing import AssistantMessage, EchoCall, Step
from agent_core.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from openai_utils.model import UserMessage


@pytest.fixture
def make_echo_calls():
    """Factory for creating EchoCall steps for echo server."""

    def _make(count: int) -> list[Step]:
        return [EchoCall(f"call{i}") for i in range(1, count + 1)]

    return _make


@pytest.fixture
def make_agent_with_turn_limit(mcp_client_echo, recording_handler, make_step_runner):
    """Factory for creating agents with turn limit."""

    async def _make(steps: list[Step], max_turns: int):
        runner = make_step_runner(steps=steps)
        return await Agent.create(
            mcp_client=mcp_client_echo,
            client=runner,
            handlers=[FinishOnTextMessageHandler(), recording_handler, MaxTurnsHandler(max_turns=max_turns)],
            tool_policy=RequireAnyTool(),
        )

    return _make


async def test_turn_limit_exceeded(make_agent_with_turn_limit, make_echo_calls) -> None:
    """Test that MaxTurnsHandler raises MaxTurnsExceededError when limit is exceeded."""
    # Setup: agent will try to make 4 calls, but we limit to 3 turns
    agent = await make_agent_with_turn_limit(
        steps=[*make_echo_calls(4)],  # 4 calls but limit to 3
        max_turns=3,
    )
    agent.insert_message(UserMessage.text("keep calling echo"))

    # Run should raise MaxTurnsExceededError on 4th sampling attempt
    with pytest.raises(MaxTurnsExceededError) as exc_info:
        await agent.run()

    # Verify error message
    assert "exceeded maximum allowed turns (3)" in str(exc_info.value).lower()
    assert "stuck in a loop" in str(exc_info.value).lower()


async def test_turn_limit_within_bounds(make_agent_with_turn_limit, make_echo_calls) -> None:
    """Test that agent completes successfully when staying within turn limit."""
    # Setup: agent makes 2 calls and finishes, limit is 5
    agent = await make_agent_with_turn_limit(steps=[*make_echo_calls(2), AssistantMessage("done")], max_turns=5)
    agent.insert_message(UserMessage.text("call echo twice"))

    # Should complete successfully
    result = await agent.run()
    assert result.text.strip() == "done"


async def test_turn_limit_exactly_at_boundary(make_agent_with_turn_limit, make_echo_calls) -> None:
    """Test that agent can use exactly max_turns without error."""
    # Setup: agent makes 2 calls then finishes (3 total turns including final assistant message)
    agent = await make_agent_with_turn_limit(steps=[*make_echo_calls(2), AssistantMessage("done")], max_turns=3)
    agent.insert_message(UserMessage.text("call echo twice"))

    # Should complete successfully (3 turns: call1, call2, done)
    result = await agent.run()
    assert result.text.strip() == "done"
