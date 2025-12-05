"""Database event handler for MiniCodex runs."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from uuid import UUID

from adgn.agent.events import AssistantText, Response, ToolCall, ToolCallOutput, UserText
from adgn.agent.handler import BaseHandler
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
            transcript_id: UUID linking this event stream to the agent run
        """
        self.transcript_id = transcript_id
        self._sequence_num = 0

    def _write_event(
        self, evt: UserText | AssistantText | ToolCall | ToolCallOutput | Response | ReasoningItem
    ) -> None:
        """Write event to database with sequence number."""
        event_type = evt.type

        with get_session() as session:
            session.add(
                Event(
                    transcript_id=self.transcript_id,
                    sequence_num=self._sequence_num,
                    event_type=event_type,
                    timestamp=datetime.now(UTC),
                    payload=evt,
                )
            )
            session.flush()

        self._sequence_num += 1
        logger.debug(f"Wrote event to DB: {self.transcript_id=} {self._sequence_num - 1=} {event_type=}")

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
