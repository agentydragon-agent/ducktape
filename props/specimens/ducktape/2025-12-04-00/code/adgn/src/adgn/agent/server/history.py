from __future__ import annotations

from collections.abc import Sequence
import logging

from pydantic import BaseModel, TypeAdapter

from adgn.agent.events import ToolCall, ToolCallOutput as RuntimeToolCallOutput, UserText
from adgn.agent.persist.events import EventRecord
from adgn.agent.server.bus import UiBusItemStructured, UiEndTurn, UiMessage
from adgn.agent.server.protocol import FunctionCallOutput, UiEndTurnEvt, UiMessageEvt, UiMessagePayload
from adgn.agent.server.reducer import reduce_ui_state
from adgn.agent.server.state import UiState, new_state

logger = logging.getLogger(__name__)

# Pre-built adapter for discriminated UI tool union
UI_ITEM_ADAPTER: TypeAdapter[UiBusItemStructured] = TypeAdapter(UiBusItemStructured)


def fold_events_to_ui_state(events: Sequence[EventRecord]) -> UiState:
    """Project canonical transcript events to UiState by folding through the reducer.

    Recognizes ui.send_message and ui.end_turn using Pydantic parsing of a
    tagged union (kind-discriminated) within function_call_output payloads.
    Falls back to a generic FunctionCallOutput projection for non-UI tools.
    """
    state = new_state()
    for ev in events:
        # UserText and ToolCall from events are already compatible with ServerMessage union
        if isinstance(ev.payload, UserText | ToolCall):
            state = reduce_ui_state(state, ev.payload)
            continue
        if isinstance(ev.payload, RuntimeToolCallOutput):
            # Safely narrow to ToolCallOutput (runtime type) and avoid casts
            structured = ev.payload.result.structuredContent
            # Live in-proc tools may return Pydantic models directly in
            # structured_content; persisted events always store JSON. Normalize
            # to the persisted JSON shape first so parsing is uniform.
            if isinstance(structured, BaseModel):
                structured = structured.model_dump(mode="json")
            # If structured is a mapping, strictly parse the tagged union. If it is
            # not a tagged UI payload, this will raise; we do not auto-heal or try to
            # coerce non-conformant shapes here.
            if isinstance(structured, dict):
                ui_item = UI_ITEM_ADAPTER.validate_python(structured)
                if isinstance(ui_item, UiEndTurn):
                    state = reduce_ui_state(state, UiEndTurnEvt())
                    continue
                if isinstance(ui_item, UiMessage):
                    state = reduce_ui_state(
                        state, UiMessageEvt(message=UiMessagePayload(mime=ui_item.mime, content=ui_item.content))
                    )
                    continue
            # Otherwise treat it as a generic non-UI tool result. FastMCP's
            # CallToolResult is not a Pydantic model; project a compact JSON
            # envelope with the native fields we rely on.
            # Embed full MCP Pydantic CallToolResult in the protocol object
            state = reduce_ui_state(state, FunctionCallOutput(call_id=ev.payload.call_id, result=ev.payload.result))
            continue
        # ignore assistant_text, reasoning, response in UI projection for now
    return state
