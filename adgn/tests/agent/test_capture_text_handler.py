"""Tests for CaptureTextHandler."""

from __future__ import annotations

import pytest

from adgn.agent.agent import Agent
from adgn.agent.handler import CaptureTextHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage
from adgn.openai_utils.model import UserMessage
from tests.support.steps import AssistantMessage, EchoCall, Step


@pytest.fixture
def capture_handler():
    """Fresh CaptureTextHandler for each test."""
    return CaptureTextHandler()


@pytest.fixture
def make_agent_with_capture(mcp_client_echo, recording_handler, capture_handler, make_step_runner):
    """Factory for creating agents with CaptureTextHandler."""

    async def _make(steps: list[Step]):
        runner = make_step_runner(steps=steps)
        return await Agent.create(
            mcp_client=mcp_client_echo,
            client=runner,
            handlers=[capture_handler, recording_handler],
            tool_policy=AllowAnyToolOrTextMessage(),
        )

    return _make


async def test_capture_text_basic(make_agent_with_capture, capture_handler) -> None:
    """Test that CaptureTextHandler captures assistant text."""
    agent = await make_agent_with_capture(steps=[AssistantMessage("Hello, world!")])
    agent.insert_message(UserMessage.text("greet me"))

    await agent.run()

    assert capture_handler.has_text
    assert capture_handler.take() == "Hello, world!"
    assert not capture_handler.has_text  # Cleared after take()


async def test_capture_text_after_tool_call(make_agent_with_capture, capture_handler) -> None:
    """Test capture after agent makes a tool call then responds."""
    agent = await make_agent_with_capture(
        steps=[
            EchoCall("testing"),
            AssistantMessage("Tool call completed."),
        ]
    )
    agent.insert_message(UserMessage.text("use echo then respond"))

    await agent.run()

    assert capture_handler.take() == "Tool call completed."


async def test_capture_text_multiple_runs(make_agent_with_capture, capture_handler) -> None:
    """Test capture across multiple agent runs (conversational pattern)."""
    agent = await make_agent_with_capture(
        steps=[
            AssistantMessage("First response"),
            AssistantMessage("Second response"),
        ]
    )

    # First run
    agent.insert_message(UserMessage.text("first question"))
    await agent.run()
    assert capture_handler.take() == "First response"

    # Second run (handler state reset after take)
    agent.insert_message(UserMessage.text("second question"))
    await agent.run()
    assert capture_handler.take() == "Second response"


async def test_capture_text_not_captured_raises(capture_handler) -> None:
    """Test that take() raises when no text was captured."""
    with pytest.raises(ValueError, match="No text captured"):
        capture_handler.take()


async def test_has_text_property(capture_handler) -> None:
    """Test has_text property without consuming the text."""
    from adgn.agent.events import AssistantText

    assert not capture_handler.has_text

    # Simulate receiving text event
    capture_handler.on_assistant_text_event(AssistantText(text="test"))

    assert capture_handler.has_text
    assert capture_handler.has_text  # Still true, not consumed

    # Now consume it
    text = capture_handler.take()
    assert text == "test"
    assert not capture_handler.has_text
