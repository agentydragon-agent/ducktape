from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID

from adgn.agent.handler import AssistantText, BaseHandler, Response, ToolCall, ToolCallOutput, UserText
from adgn.mcp._shared.calltool import convert_fastmcp_result
from adgn.openai_utils.model import ReasoningItem

from . import EventType, Persistence
from .events import (
    AssistantTextPayload,
    FunctionCallOutputPayload,
    ReasoningPayload,
    ResponsePayload,
    ToolCallPayload,
    TypedPayload,
    UserTextPayload,
)

logger = logging.getLogger("adgn.persist.handler")


class RunPersistenceHandler(BaseHandler):
    """Ever-present handler that appends canonical transcript items to persistence.

    Uses an explicit run binding so it can remain attached across runs.
    """

    def __init__(self, *, persistence: Persistence, get_run_id: Callable[[], UUID | None] | None = None) -> None:
        self._persistence = persistence
        self._get_run_id = get_run_id
        self._current_run_id: UUID | None = None
        self._last_run_id: UUID | None = None
        self._seq = 0
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro: Any) -> None:
        t: asyncio.Task = asyncio.create_task(coro)
        self._tasks.add(t)

        def _done(task: asyncio.Task) -> None:
            self._tasks.discard(task)
            exc = task.exception()
            if exc:
                logger.exception("persistence task failed", exc_info=exc)

        t.add_done_callback(_done)

    def bind_run(self, run_id: UUID) -> None:
        """Explicitly bind to a run. Primarily for legacy call sites.

        When a get_run_id callback is provided, this is optional; the handler
        will automatically pick up the active run id.
        """
        self._current_run_id = run_id
        self._last_run_id = run_id
        self._seq = 0

    def end_run(self) -> None:
        self._current_run_id = None
        self._seq = 0

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def drain(self) -> None:
        """Wait for all in-flight persistence tasks to finish.

        Raises RuntimeError if any task failed. Callers can decide whether to
        proceed with destructive actions (like purge) or abort.
        """
        pending: list[asyncio.Task] = list(self._tasks)
        if not pending:
            return
        results = await asyncio.gather(*pending, return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            # Summarize unique error types for clarity
            kinds = sorted({type(e).__name__ for e in errors})
            raise RuntimeError(f"persistence_drain_failed: {', '.join(kinds)}")

    def _record_event(
        self, *, type: EventType, payload: TypedPayload, call_id: str | None = None, tool_key: str | None = None
    ) -> None:
        """Common append path: guard run, bump seq, enqueue append_event.

        Keeps ordering by incrementing a local sequence per run.
        """
        rid = self._current_run_id or (self._get_run_id() if self._get_run_id else None)
        if rid is None:
            return
        # Reset sequence if run changed (auto-bind path)
        if self._last_run_id != rid:
            self._last_run_id = rid
            self._seq = 0
        self._seq += 1
        self._spawn(
            self._persistence.append_event(
                run_id=rid,
                seq=self._seq,
                ts=self._now(),
                type=type,
                payload=payload,
                call_id=call_id,
                tool_key=tool_key,
            )
        )

    # BaseHandler typed hooks --------------------------------------------------
    def on_user_text_event(self, evt: UserText) -> None:
        self._record_event(type=EventType.USER_TEXT, payload=UserTextPayload(text=evt.text))

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        self._record_event(type=EventType.ASSISTANT_TEXT, payload=AssistantTextPayload(text=evt.text))

    def on_tool_call_event(self, evt: ToolCall) -> None:
        self._record_event(
            type=EventType.TOOL_CALL,
            payload=ToolCallPayload(name=evt.name, args_json=evt.args_json, call_id=evt.call_id),
            call_id=evt.call_id,
            tool_key=evt.name,
        )

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        self._record_event(
            type=EventType.FUNCTION_CALL_OUTPUT,
            payload=FunctionCallOutputPayload(
                call_id=evt.call_id,
                result=convert_fastmcp_result(evt.result)
            ),
            call_id=evt.call_id,
        )

    def on_reasoning(self, item: ReasoningItem) -> None:
        self._record_event(type=EventType.REASONING, payload=ReasoningPayload(text=item.text))

    def on_response(self, evt: Response) -> None:
        self._record_event(type=EventType.RESPONSE, payload=ResponsePayload(content=evt))
