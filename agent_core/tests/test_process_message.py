"""Tests for process_message handler notification."""

from __future__ import annotations

from agent_core.agent import Agent
from agent_core.events import AssistantText, SystemText, UserText
from agent_core.loop_control import AllowAnyToolOrTextMessage
from agent_core.testing.openai_mock import NoopOpenAIClient
from openai_utils.model import AssistantMessage, SystemMessage, UserMessage

# Uses 'recording_handler' fixture from agent_core.testing.fixtures via conftest.py


async def test_process_message_fires_system_text_event(compositor_client, recording_handler) -> None:
    """Test that process_message fires on_system_text_event for SystemMessage."""
    agent = await Agent.create(
        mcp_client=compositor_client,
        client=NoopOpenAIClient(),
        handlers=[recording_handler],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(SystemMessage.text("System prompt content"))

    assert len(recording_handler.text_events) == 1
    assert isinstance(recording_handler.text_events[0], SystemText)
    assert recording_handler.text_events[0].text == "System prompt content"


async def test_process_message_fires_user_text_event(compositor_client, recording_handler) -> None:
    """Test that process_message fires on_user_text_event for UserMessage."""
    agent = await Agent.create(
        mcp_client=compositor_client,
        client=NoopOpenAIClient(),
        handlers=[recording_handler],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(UserMessage.text("User says hello"))

    assert len(recording_handler.text_events) == 1
    assert isinstance(recording_handler.text_events[0], UserText)
    assert recording_handler.text_events[0].text == "User says hello"


async def test_process_message_fires_assistant_text_event(compositor_client, recording_handler) -> None:
    """Test that process_message fires on_assistant_text_event for AssistantMessage."""
    agent = await Agent.create(
        mcp_client=compositor_client,
        client=NoopOpenAIClient(),
        handlers=[recording_handler],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(AssistantMessage.text("Assistant response"))

    assert len(recording_handler.text_events) == 1
    assert isinstance(recording_handler.text_events[0], AssistantText)
    assert recording_handler.text_events[0].text == "Assistant response"


async def test_process_message_adds_to_transcript(compositor_client, recording_handler) -> None:
    """Test that process_message adds messages to transcript."""
    agent = await Agent.create(
        mcp_client=compositor_client,
        client=NoopOpenAIClient(),
        handlers=[recording_handler],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(SystemMessage.text("Sys"))
    agent.process_message(UserMessage.text("Usr"))

    assert len(agent._transcript) == 2
    assert isinstance(agent._transcript[0], SystemMessage)
    assert isinstance(agent._transcript[1], UserMessage)
    # Both should have fired events
    assert len(recording_handler.text_events) == 2
