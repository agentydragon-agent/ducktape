from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from typing import Any

from adgn.agent.handler import AssistantText, BaseHandler, Response, ToolCall, ToolCallOutput, UserText
from adgn.agent.types import AgentID
from adgn.mcp._shared.calltool import to_pydantic
from adgn.openai_utils.model import ReasoningItem

from . import Persistence

logger = logging.getLogger("adgn.persist.handler")


class RunPersistenceHandler(BaseHandler):
    """Ever-present handler that appends canonical transcript items to persistence."""

    def __init__(self, *, persistence: Persistence, agent_id: AgentID) -> None:
        self._persistence = persistence
        self._agent_id = agent_id
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
        self, *, payload: dict[str, Any], call_id: str | None = None, tool_key: str | None = None
    ) -> None:
        """Common append path: bump seq, enqueue append_event.

        Keeps ordering by incrementing a local sequence.
        Payload must contain 'type' field for discriminated union.
        """
        self._seq += 1
        self._spawn(
            self._persistence.append_event(
                agent_id=self._agent_id,
                seq=self._seq,
                ts=self._now(),
                payload=payload,
                call_id=call_id,
                tool_key=tool_key,
            )
        )

    # BaseHandler typed hooks --------------------------------------------------
    def on_user_text_event(self, evt: UserText) -> None:
        payload = evt.model_dump(mode="json", exclude_none=True)
        payload["type"] = "user_text"
        self._record_event(payload=payload)

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        payload = evt.model_dump(mode="json", exclude_none=True)
        payload["type"] = "assistant_text"
        self._record_event(payload=payload)

    def on_tool_call_event(self, evt: ToolCall) -> None:
        payload = evt.model_dump(mode="json", exclude_none=True)
        payload["type"] = "tool_call"
        self._record_event(payload=payload, call_id=evt.call_id, tool_key=evt.name)

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        # Persist full Pydantic MCP CallToolResult (with content when available)
        payload_model = to_pydantic(evt.result)
        payload = payload_model.model_dump(mode="json", by_alias=True)
        payload["type"] = "function_call_output"
        payload["call_id"] = evt.call_id
        self._record_event(payload=payload, call_id=evt.call_id)

    def on_reasoning(self, item: ReasoningItem) -> None:
        payload = item.model_dump(mode="json", exclude_none=True)
        payload["type"] = "reasoning"
        self._record_event(payload=payload)

    def on_response(self, evt: Response) -> None:
        payload = evt.model_dump(mode="json", exclude_none=True)
        payload["type"] = "response"
        self._record_event(payload=payload)
