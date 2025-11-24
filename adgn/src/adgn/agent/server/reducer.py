from __future__ import annotations

import json

from mcp import types as mcp_types

from adgn.agent.approvals import WellKnownTools
from adgn.agent.server.protocol import (
    ApprovalDecisionEvt,
    FunctionCallOutput,
    ToolCall,
    UiEndTurnEvt,
    UiMessageEvt,
    UserText,
)
from adgn.mcp._shared.constants import UI_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function

from .state import (
    AssistantMarkdownItem,
    EndTurnItem,
    ToolItem,
    UiState,
    UserMessageItem,
    append_item,
    start_tool,
    update_tool_decision,
    update_tool_exec_stream,
    update_tool_json_output,
)

# Union type for all supported UI state events
UiStateEvent = UserText | ToolCall | FunctionCallOutput | ApprovalDecisionEvt | UiMessageEvt | UiEndTurnEvt


def reduce_ui_state(state: UiState, evt: UiStateEvent) -> UiState:
    """Pure reducer: match by Pydantic type; never treat models as dicts.

    Args:
        state: Current UI state.
        evt: Event to apply (one of the UiStateEvent union types).

    Returns:
        Updated UI state with the event applied.

    Accepted event types:
    - UserText: User text input
    - ToolCall: Tool call start event
    - FunctionCallOutput: Tool execution output
    - ApprovalDecisionEvt: Approval decision event
    - UiMessageEvt: Assistant message event
    - UiEndTurnEvt: End turn separator event
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
        if evt.name in (
            build_mcp_function(UI_SERVER_NAME, WellKnownTools.SEND_MESSAGE),
            build_mcp_function(UI_SERVER_NAME, WellKnownTools.END_TURN),
        ):
            return state
        return start_tool(state, tool=evt.name, call_id=evt.call_id, cmd=cmd, args=parsed_args)

    # Approval decision → add to the current group
    if isinstance(evt, ApprovalDecisionEvt):
        return update_tool_decision(state, evt.call_id, decision=evt.decision.kind)

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
            if isinstance(it, ToolItem) and it.call_id == evt.call_id:
                tool_name = it.tool
                break
        if tool_name in (
            build_mcp_function(UI_SERVER_NAME, WellKnownTools.SEND_MESSAGE),
            build_mcp_function(UI_SERVER_NAME, WellKnownTools.END_TURN),
        ):
            return state

        # Store the typed CallToolResult directly (Pydantic handles JSON serialization)
        return update_tool_json_output(state, evt.call_id, result=res, is_error=is_error)

    # Unknown event → no-op
    return state
