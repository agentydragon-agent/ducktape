"""Tests for transcript compaction."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.compaction import CompactionHandler
from adgn.agent.events import GroundTruthUsage, Response
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Compact, NoAction, RequireAnyTool
from adgn.openai_utils.model import AssistantMessage, AssistantMessageOut, OutputText, UserMessage


class MockOpenAIClient:
    """Mock OpenAI client for testing."""

    def __init__(self):
        self.model = "gpt-4o-mini-test"
        self.responses_create = AsyncMock()

    async def setup_summary_response(self, summary_text: str):
        """Configure the mock to return a specific summary."""
        mock_response = Mock()
        mock_response.id = "test-response-id"
        mock_response.usage = None
        mock_response.output = [AssistantMessageOut(parts=[OutputText(text=summary_text)])]
        self.responses_create.return_value = mock_response


@pytest.fixture
def mock_openai():
    """Create a mock OpenAI client for testing."""
    return MockOpenAIClient()


@pytest.mark.asyncio
async def test_compact_transcript_basic(compositor_client, mock_openai):
    """Test basic transcript compaction."""
    await mock_openai.setup_summary_response("User asked about compaction. Assistant explained the concept.")

    agent = await MiniCodex.create(
        mcp_client=compositor_client,
        client=mock_openai,
        handlers=[BaseHandler()],
        system="Test system prompt",
        tool_policy=RequireAnyTool(),
    )

    # Add some conversation history to the transcript
    agent._transcript.extend(
        [
            UserMessage.text("What is compaction?"),
            AssistantMessage.text("Compaction is a technique for managing limited context windows."),
            UserMessage.text("How does it work?"),
            AssistantMessage.text("It summarizes old messages to save tokens."),
            UserMessage.text("Can you give an example?"),
            AssistantMessage.text("Sure, here is an example..."),
        ]
    )

    # Compact with keep_recent_turns=2 (should keep last 2 exchanges)
    result = await agent.compact_transcript(keep_recent_turns=2)

    # Verify compaction happened
    assert result.compacted

    # Verify transcript structure
    # Should have: [summary, last 2 user/assistant pairs]
    assert len(agent._transcript) == 3  # summary + 2 recent messages
    # Type narrow to check content
    item0 = agent._transcript[0]
    assert isinstance(item0, UserMessage | AssistantMessage)
    assert item0.content is not None
    # Check that the summary text is present (no longer wrapped in tags)
    assert "User asked about compaction" in item0.content[0].text
    item1 = agent._transcript[1]
    assert isinstance(item1, UserMessage | AssistantMessage)
    assert item1.content is not None
    assert item1.content[0].text == "Can you give an example?"
    item2 = agent._transcript[2]
    assert isinstance(item2, UserMessage | AssistantMessage)
    assert item2.content is not None
    assert item2.content[0].text == "Sure, here is an example..."

    # Verify summarization was called
    mock_openai.responses_create.assert_called_once()


@pytest.mark.asyncio
async def test_compact_transcript_insufficient_history(compositor_client, mock_openai):
    """Test that compaction doesn't happen when history is too short."""
    agent = await MiniCodex.create(
        mcp_client=compositor_client,
        client=mock_openai,
        handlers=[BaseHandler()],
        system="Test system prompt",
        tool_policy=RequireAnyTool(),
    )

    # Add only a few messages
    agent._transcript.extend([UserMessage.text("Hello"), AssistantMessage.text("Hi there")])

    # Try to compact with keep_recent_turns=10 (more than we have)
    result = await agent.compact_transcript(keep_recent_turns=10)

    # Verify compaction didn't happen
    assert not result.compacted

    # Transcript unchanged
    assert len(agent._transcript) == 2  # 2 messages

    # No summarization call
    mock_openai.responses_create.assert_not_called()


@pytest.mark.asyncio
async def test_compaction_handler_triggers_at_threshold(compositor_client, mock_openai):
    """Test that CompactionHandler tracks tokens and returns Compact decision when threshold exceeded."""
    # Create compaction handler with low threshold
    handler = CompactionHandler(threshold_tokens=1000, keep_recent_turns=2)

    # Simulate token usage below threshold
    handler.on_response(
        Response(
            response_id="test-id", usage=GroundTruthUsage(model="gpt-4o-mini", total_tokens=500), model="gpt-4o-mini"
        )
    )
    decision = handler.on_before_sample()
    assert isinstance(decision, NoAction)  # Not ready to compact yet

    # Simulate token usage exceeding threshold
    handler.on_response(
        Response(
            response_id="test-id2", usage=GroundTruthUsage(model="gpt-4o-mini", total_tokens=600), model="gpt-4o-mini"
        )
    )
    decision = handler.on_before_sample()
    assert isinstance(decision, Compact)  # Should trigger compaction
    assert decision.keep_recent_turns == 2

    # Second check should return NoAction (only compact once)
    decision = handler.on_before_sample()
    assert isinstance(decision, NoAction)


@pytest.mark.asyncio
async def test_compaction_handler_integrated_with_agent(compositor_client, mock_openai):
    """Test that CompactionHandler works when integrated with agent loop."""
    await mock_openai.setup_summary_response("Summary of early conversation.")

    # Create agent with compaction handler (low threshold for testing)
    handler = CompactionHandler(threshold_tokens=100, keep_recent_turns=2)

    agent = await MiniCodex.create(
        mcp_client=compositor_client,
        client=mock_openai,
        handlers=[handler],
        system="Test system prompt",
        tool_policy=RequireAnyTool(),
    )

    # Add conversation history
    agent._transcript.extend(
        [
            UserMessage.text("First message"),
            AssistantMessage.text("First response"),
            UserMessage.text("Second message"),
            AssistantMessage.text("Second response"),
            UserMessage.text("Third message"),
            AssistantMessage.text("Third response"),
        ]
    )

    # Trigger compaction by simulating token usage
    handler.on_response(
        Response(
            response_id="test-response",
            usage=GroundTruthUsage(model="gpt-4o-mini", total_tokens=150),
            model="gpt-4o-mini",
        )
    )

    # Manually trigger compaction (in real agent loop, _run_one_phase would do this)
    decision = handler.on_before_sample()
    assert isinstance(decision, Compact)
    await agent.compact_transcript(keep_recent_turns=decision.keep_recent_turns)

    # Verify transcript was compacted
    assert len(agent._transcript) < 6  # Original was 6 messages
    # Check that summary text is present (no longer wrapped in tags)
    assert any("Summary of early conversation" in str(item) for item in agent._transcript)
