from __future__ import annotations

import json
from typing import Any

from adgn.agent.ui.protocol import (
    UserText,
    ToolCall,
    FunctionCallOutput,
    ApprovalDecisionEvt,
    UiMessageEvt,
    UiEndTurnEvt,
)
from adgn.agent.mcp_manager import build_mcp_function

from .state import (
    UiState,
    UserMessageItem,
    AssistantMarkdownItem,
    EndTurnItem,
    ToolItem,
    append_item,
    start_tool,
    update_tool_decision,
    update_tool_exec_stream,
    update_tool_json_output,
)


def reduce_ui_state(state: UiState, evt: Any) -> UiState:
    """Pure reducer: match by Pydantic type; never treat models as dicts.

    Accepted types:
    - UserText
    - ToolCall
    - FunctionCallOutput
    - ApprovalDecisionEvt
    - UiMessageEvt
    - UiEndTurnEvt
    """
    # User message
    if isinstance(evt, UserText):
        return UiState(
            seq=state.seq + 1, items=[*state.items, UserMessageItem(text=evt.text)]
        )

    # Assistant markdown (from ui.send_message)
    if isinstance(evt, UiMessageEvt):
        md = evt.message.content
        return UiState(
            seq=state.seq + 1, items=[*state.items, AssistantMarkdownItem(md=md)]
        )

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
                argv = (
                    args.get("argv") or args.get("cmd")
                    if isinstance(args, dict)
                    else None
                )
                if isinstance(argv, list):
                    # shell-join with conservative quoting
                    parts: list[str] = []
                    for a in argv:
                        if (
                            isinstance(a, str)
                            and a
                            and all(ch.isalnum() or ch in "_./-" for ch in a)
                        ):
                            parts.append(a)
                        else:
                            s = str(a).replace("'", "'\\''")
                            parts.append(f"'{s}'")
                    cmd = " ".join(parts)
            except Exception:
                cmd = None
                parsed_args = None
        # For ui.send_message and ui.end_turn: do not create a ToolItem; UiMessageEvt/UiEndTurnEvt after execution will surface AssistantMarkdown/EndTurn
        if evt.name in (
            build_mcp_function("ui", "send_message"),
            build_mcp_function("ui", "end_turn"),
        ):
            return state
        return start_tool(
            state, tool=evt.name, call_id=evt.call_id, cmd=cmd, args=parsed_args
        )

    # Approval decision → add to the current group
    if isinstance(evt, ApprovalDecisionEvt):
        return update_tool_decision(state, evt.call_id, decision=evt.decision.kind)

    # Function call output → merge stdout/stderr/exit
    if isinstance(evt, FunctionCallOutput):
        result_dict = evt.result or {}
        structured = result_dict.get("structuredContent")
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
        is_error = bool(result_dict.get("isError"))

        next_state = update_tool_exec_stream(
            state,
            evt.call_id,
            stdout=stdout,
            stderr=stderr,
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
            build_mcp_function("ui", "send_message"),
            build_mcp_function("ui", "end_turn"),
        ):
            return state

        result_payload = result_dict if result_dict else None
        return update_tool_json_output(
            state,
            evt.call_id,
            result=result_payload,
            is_error=is_error,
        )

    # Unknown event → no-op
    return state
