from __future__ import annotations

from collections.abc import Sequence
import json

from mcp import types as mcp_types
from pydantic import BaseModel, TypeAdapter

from adgn.agent.events import (
    ToolCall as RuntimeToolCall,
    ToolCallOutput as RuntimeToolCallOutput,
    UserText as RuntimeUserText,
)
from adgn.agent.persist.events import EventRecord
from adgn.agent.server.bus import UiBusItemStructured, UiEndTurn, UiMessage
from adgn.agent.server.protocol import (
    FunctionCallOutput,
    ServerMessage,
    ToolCall,
    UiEndTurnEvt,
    UiMessageEvt,
    UiMessagePayload,
    UserText,
)
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.ui.server import UiServer

from .state import (
    AssistantMarkdownItem,
    EndTurnItem,
    ToolItem,
    UiState,
    UserMessageItem,
    append_item,
    new_state,
    start_tool,
    update_tool_exec_stream,
    update_tool_json_output,
)

# Pre-built adapter for discriminated UI tool union
UI_ITEM_ADAPTER: TypeAdapter[UiBusItemStructured] = TypeAdapter(UiBusItemStructured)


class Reducer:
    """UI state reducer with access to mounted UI server."""

    def __init__(self, ui_mount: Mounted[UiServer] | None):
        """Create a reducer.

        Args:
            ui_mount: Mounted UI server (for computing tool names), None if UI is disabled
        """
        self._ui_mount = ui_mount

    def reduce(self, state: UiState, evt: ServerMessage) -> UiState:
        """Reduce UI state based on server message event.

        Args:
            state: Current UI state
            evt: Server message event to process

        Returns:
            New UI state after applying the event

        Accepted types:
        - UserText
        - ToolCall
        - FunctionCallOutput
        - UiMessageEvt
        - UiEndTurnEvt
        """
        # User message
        if isinstance(evt, UserText):
            return UiState(seq=state.seq + 1, items=[*state.items, UserMessageItem(text=evt.text)])

        # Assistant markdown (from ui.send_message)
        if isinstance(evt, UiMessageEvt):
            md = evt.message.content
            return UiState(seq=state.seq + 1, items=[*state.items, AssistantMarkdownItem(md=md)])

        # End turn separator (from ui.end_turn)
        if isinstance(evt, UiEndTurnEvt):
            return append_item(state, EndTurnItem())

        # Tool call start → begin a group (attempt to derive cmd from args_json for exec tools)
        if isinstance(evt, ToolCall):
            cmd: str | None = None
            parsed_args: dict | None = None
            if evt.args_json:
                try:
                    args = json.loads(evt.args_json)
                    parsed_args = args if isinstance(args, dict) else None
                    argv = args.get("argv") or args.get("cmd") if isinstance(args, dict) else None
                    if isinstance(argv, list):
                        # shell-join with conservative quoting
                        parts: list[str] = []
                        for a in argv:
                            if isinstance(a, str) and a and all(ch.isalnum() or ch in "_./-" for ch in a):
                                parts.append(a)
                            else:
                                s = str(a).replace("'", "'\\''")
                                parts.append(f"'{s}'")
                        cmd = " ".join(parts)
                except json.JSONDecodeError:
                    cmd = None
                    parsed_args = None
            # For ui.send_message and ui.end_turn: do not create a ToolItem; UiMessageEvt/UiEndTurnEvt after execution will surface AssistantMarkdown/EndTurn
            if self._ui_mount is not None:
                ui_tool_names = {
                    build_mcp_function(self._ui_mount.prefix, self._ui_mount.server.send_message_tool.name),
                    build_mcp_function(self._ui_mount.prefix, self._ui_mount.server.end_turn_tool.name),
                }
                if evt.name in ui_tool_names:
                    return state
            elif evt.name in {"ui_send_message", "ui_end_turn"}:
                # Fallback for tests/replay when ui_mount is not available
                return state
            return start_tool(state, tool_call=evt, cmd=cmd, args=parsed_args)

        # Function call output → merge stdout/stderr/exit
        if isinstance(evt, FunctionCallOutput):
            res = evt.result
            if not isinstance(res, mcp_types.CallToolResult):
                raise TypeError(f"FunctionCallOutput.result must be mcp.types.CallToolResult, got {type(res).__name__}")
            structured = res.structuredContent
            stdout = stderr = None
            exit_code = None
            if isinstance(structured, dict):
                stdout = structured.get("stdout_text") or structured.get("stdout")
                stderr = structured.get("stderr_text") or structured.get("stderr")
                exit_code_val = structured.get("exit_code")
                if isinstance(exit_code_val, int):
                    exit_code = exit_code_val
                elif exit_code_val is not None:
                    try:
                        exit_code = int(exit_code_val)
                    except (TypeError, ValueError):
                        exit_code = None
            is_error = bool(res.isError)
            # If tool reported an error without structured streams, surface a message via stderr
            error_message: str | None = None
            if is_error and not stderr and isinstance(structured, dict):
                # Best-effort message discovery for common fields
                msg = structured.get("error") or structured.get("message") or structured.get("detail")
                if isinstance(msg, str):
                    error_message = msg

            next_state = update_tool_exec_stream(
                state,
                evt.call_id,
                stdout=stdout,
                stderr=(stderr if stderr is not None else error_message),
                exit_code=exit_code,
                is_error=is_error,
            )
            if next_state is not state:
                return next_state

            tool_name: str | None = None
            for it in reversed(state.items):
                if isinstance(it, ToolItem) and it.tool_call.call_id == evt.call_id:
                    tool_name = it.tool_call.name
                    break

            # Check if this is a UI tool call (these don't get stored as ToolItems)
            if tool_name is not None:
                if self._ui_mount is not None:
                    ui_tool_names = {
                        build_mcp_function(self._ui_mount.prefix, self._ui_mount.server.send_message_tool.name),
                        build_mcp_function(self._ui_mount.prefix, self._ui_mount.server.end_turn_tool.name),
                    }
                    if tool_name in ui_tool_names:
                        return state
                elif tool_name in {"ui_send_message", "ui_end_turn"}:
                    # Fallback for tests/replay when ui_mount is not available
                    return state

            # Store the typed CallToolResult directly (Pydantic handles JSON serialization)
            return update_tool_json_output(state, evt.call_id, result=res, is_error=is_error)

        # Unknown event → no-op
        return state


def fold_events_to_ui_state(events: Sequence[EventRecord]) -> UiState:
    """Project canonical transcript events to UiState by folding through the reducer.

    Recognizes ui.send_message and ui.end_turn using Pydantic parsing of a
    tagged union (kind-discriminated) within function_call_output payloads.
    Falls back to a generic FunctionCallOutput projection for non-UI tools.
    """
    reducer = Reducer(ui_mount=None)
    state = new_state()
    for ev in events:
        # UserText and ToolCall from events are already compatible with ServerMessage union
        if isinstance(ev.payload, RuntimeUserText | RuntimeToolCall):
            state = reducer.reduce(state, ev.payload)
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
                    state = reducer.reduce(state, UiEndTurnEvt())
                    continue
                if isinstance(ui_item, UiMessage):
                    state = reducer.reduce(
                        state, UiMessageEvt(message=UiMessagePayload(mime=ui_item.mime, content=ui_item.content))
                    )
                    continue
            # Otherwise treat it as a generic non-UI tool result. FastMCP's
            # CallToolResult is not a Pydantic model; project a compact JSON
            # envelope with the native fields we rely on.
            # Embed full MCP Pydantic CallToolResult in the protocol object
            state = reducer.reduce(state, FunctionCallOutput(call_id=ev.payload.call_id, result=ev.payload.result))
            continue
        # ignore assistant_text, reasoning, response in UI projection for now
    return state
