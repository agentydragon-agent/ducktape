"""Tests for process_message handler notification."""

from __future__ import annotations

from agent_core.events import AssistantText, SystemText, UserText
from openai_utils.model import AssistantMessage, SystemMessage, UserMessage


async def test_process_message_fires_system_text_event(noop_agent, recording_handler) -> None:
    """Test that process_message fires on_system_text_event for SystemMessage."""
    noop_agent.process_message(SystemMessage.text("System prompt content"))

    assert len(recording_handler.text_events) == 1
    assert isinstance(recording_handler.text_events[0], SystemText)
    assert recording_handler.text_events[0].text == "System prompt content"


async def test_process_message_fires_user_text_event(noop_agent, recording_handler) -> None:
    """Test that process_message fires on_user_text_event for UserMessage."""
    noop_agent.process_message(UserMessage.text("User says hello"))

    assert len(recording_handler.text_events) == 1
    assert isinstance(recording_handler.text_events[0], UserText)
    assert recording_handler.text_events[0].text == "User says hello"


async def test_process_message_fires_assistant_text_event(noop_agent, recording_handler) -> None:
    """Test that process_message fires on_assistant_text_event for AssistantMessage."""
    noop_agent.process_message(AssistantMessage.text("Assistant response"))

    assert len(recording_handler.text_events) == 1
    assert isinstance(recording_handler.text_events[0], AssistantText)
    assert recording_handler.text_events[0].text == "Assistant response"


async def test_process_message_adds_to_transcript(noop_agent, recording_handler) -> None:
    """Test that process_message adds messages to transcript."""
    noop_agent.process_message(SystemMessage.text("Sys"))
    noop_agent.process_message(UserMessage.text("Usr"))

    assert len(noop_agent._transcript) == 2
    assert isinstance(noop_agent._transcript[0], SystemMessage)
    assert isinstance(noop_agent._transcript[1], UserMessage)
    # Both should have fired events
    assert len(recording_handler.text_events) == 2
