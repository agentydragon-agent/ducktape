from __future__ import annotations

import logging
from typing import Sequence

from adgn.agent.persist.events import EventRecord, FunctionCallOutputPayload
from adgn.agent.server.bus import UiEndTurn, UiMessage
from adgn.agent.server.protocol import (
    FunctionCallOutput,
    ToolCall,
    UiEndTurnEvt,
    UiMessageEvt,
    UiMessagePayload,
    UserText,
)
from adgn.agent.server.reducer import reduce_ui_state
from adgn.agent.server.state import UiState, new_state

logger = logging.getLogger(__name__)


def fold_events_to_ui_state(events: Sequence[EventRecord]) -> UiState:
    """Project canonical transcript events to UiState by folding through the reducer.

    Recognizes ui.send_message and ui.end_turn by structuredContent shape within
    function_call_output payloads and falls back to generic tool output projection.
    """
    state = new_state()
    for ev in events:
        et = ev.type.value
        payload = ev.payload.model_dump(mode="json")
        if et == "user_text":
            state = reduce_ui_state(state, UserText(text=str(payload.get("text", ""))))
            continue
        if et == "tool_call":
            state = reduce_ui_state(
                state,
                ToolCall(
                    name=payload.get("name", ""),
                    args_json=payload.get("args_json"),
                    call_id=payload.get("call_id") or ev.call_id or "",
                ),
            )
            continue
        if et == "function_call_output":
            # Typed result: access structuredContent via explicit attribute on CallToolResult
            fco: FunctionCallOutputPayload = ev.payload  # type: ignore[assignment]
            structured = fco.result.structuredContent
            if isinstance(structured, dict):
                # Recognize end_turn; validation errors are surfaced
                if structured.get("kind") == "EndTurn":
                    UiEndTurn.model_validate(structured)
                    state = reduce_ui_state(state, UiEndTurnEvt())
                    continue
                # Recognize ui.send_message payloads by presence of content (and optional mime)
                if isinstance(structured.get("content"), str):
                    msg = UiMessage.model_validate(structured)
                    state = reduce_ui_state(
                        state,
                        UiMessageEvt(message=UiMessagePayload(mime=msg.mime, content=msg.content)),
                    )
                    continue
            # Fallback: record generic function call output (for non-UI tools)
            # Serialize typed CallToolResult back to JSON for the reducer fallback
            result_json = fco.result.model_dump(mode="json")  # type: ignore[attr-defined]
            state = reduce_ui_state(
                state,
                FunctionCallOutput(
                    call_id=ev.call_id or "",
                    result=result_json,  # type: ignore[arg-type]
                ),
            )
            continue
        # ignore assistant_text, reasoning, response in UI projection for now
    return state
