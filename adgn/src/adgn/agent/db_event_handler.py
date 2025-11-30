"""Database event handler for MiniCodex runs.

Writes agent events to the database events table instead of events.jsonl files.
Each event is linked to the agent run via transcript_id and sequenced.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from uuid import UUID

from adgn.agent.handler import AssistantText, BaseHandler, Response, ToolCall, ToolCallOutput, UserText, to_jsonl_record
from adgn.agent.loop_control import NoLoopDecision
from adgn.openai_utils.model import ReasoningItem
from adgn.props.db import get_session
from adgn.props.db.models import Event

logger = logging.getLogger(__name__)


class DatabaseEventHandler(BaseHandler):
    """Database event writer for MiniCodex runs.

    Writes events to the database events table, maintaining sequence order.
    Each event is linked to the agent run via transcript_id.

    Usage:
        from uuid import UUID
        handler = DatabaseEventHandler(transcript_id=UUID('...'))
        MiniCodex.create(..., handlers=[handler, ...])
    """

    def __init__(self, *, transcript_id: UUID) -> None:
        """Initialize handler for a specific agent run.

        Args:
            transcript_id: UUID linking this event stream to critic/grader runs
        """
        self.transcript_id = transcript_id
        self._sequence_num = 0

    def _write_event(
        self, evt: UserText | AssistantText | ToolCall | ToolCallOutput | Response | ReasoningItem
    ) -> None:
        """Write event to database with sequence number.

        Args:
            evt: Event object to persist
        """
        # Convert event to JSONL record (adds 'kind' field)
        rec = to_jsonl_record(evt)

        # Extract kind and remove from payload (stored separately in event_type column)
        event_type = rec.pop("kind")

        # Write to database
        with get_session() as session:
            event = Event(
                transcript_id=self.transcript_id,
                sequence_num=self._sequence_num,
                event_type=event_type,
                timestamp=datetime.now(UTC),
                payload=rec,  # Event data without 'kind' (stored in event_type column)
            )
            session.add(event)
            session.flush()

        self._sequence_num += 1
        logger.debug(
            f"Wrote event to DB: transcript_id={self.transcript_id}, seq={self._sequence_num - 1}, type={event_type}"
        )

    # ---- BaseHandler hooks (typed) ----
    def on_user_text_event(self, evt: UserText) -> None:
        self._write_event(evt)

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        self._write_event(evt)

    def on_tool_call_event(self, evt: ToolCall) -> None:
        self._write_event(evt)

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        self._write_event(evt)

    def on_reasoning(self, item: ReasoningItem) -> None:
        self._write_event(item)

    def on_response(self, evt: Response) -> None:
        self._write_event(evt)

    def on_before_sample(self) -> NoLoopDecision:
        """Do not influence loop control."""
        return NoLoopDecision()
