"""Tests for process_message handler notification."""

from __future__ import annotations

import pytest

from agent_core.agent import Agent
from agent_core.events import AssistantText, SystemText, UserText
from agent_core.handler import BaseHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from openai_utils.model import AssistantMessage, SystemMessage, UserMessage


class RecordingHandler(BaseHandler):
    """Handler that records all events for testing."""

    def __init__(self):
        self.events: list = []

    def on_system_text_event(self, evt: SystemText) -> None:
        self.events.append(evt)

    def on_user_text_event(self, evt: UserText) -> None:
        self.events.append(evt)

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        self.events.append(evt)


@pytest.fixture
def handler():
    return RecordingHandler()


async def test_process_message_fires_system_text_event(compositor_client, handler) -> None:
    """Test that process_message fires on_system_text_event for SystemMessage."""
    agent = await Agent.create(
        mcp_client=compositor_client,
        client=None,  # Not running, just testing process_message
        handlers=[handler],
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(SystemMessage.text("System prompt content"))

    assert len(handler.events) == 1
    assert isinstance(handler.events[0], SystemText)
    assert handler.events[0].text == "System prompt content"


async def test_process_message_fires_user_text_event(compositor_client, handler) -> None:
    """Test that process_message fires on_user_text_event for UserMessage."""
    agent = await Agent.create(
        mcp_client=compositor_client, client=None, handlers=[handler], tool_policy=AllowAnyToolOrTextMessage()
    )

    agent.process_message(UserMessage.text("User says hello"))

    assert len(handler.events) == 1
    assert isinstance(handler.events[0], UserText)
    assert handler.events[0].text == "User says hello"


async def test_process_message_fires_assistant_text_event(compositor_client, handler) -> None:
    """Test that process_message fires on_assistant_text_event for AssistantMessage."""
    agent = await Agent.create(
        mcp_client=compositor_client, client=None, handlers=[handler], tool_policy=AllowAnyToolOrTextMessage()
    )

    agent.process_message(AssistantMessage.text("Assistant response"))

    assert len(handler.events) == 1
    assert isinstance(handler.events[0], AssistantText)
    assert handler.events[0].text == "Assistant response"


async def test_process_message_adds_to_transcript(compositor_client, handler) -> None:
    """Test that process_message adds messages to transcript."""
    agent = await Agent.create(
        mcp_client=compositor_client, client=None, handlers=[handler], tool_policy=AllowAnyToolOrTextMessage()
    )

    agent.process_message(SystemMessage.text("Sys"))
    agent.process_message(UserMessage.text("Usr"))

    assert len(agent._transcript) == 2
    assert isinstance(agent._transcript[0], SystemMessage)
    assert isinstance(agent._transcript[1], UserMessage)
    # Both should have fired events
    assert len(handler.events) == 2
