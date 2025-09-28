from __future__ import annotations

import json
from typing import Any

from adgn.llm.mini_codex.ui.protocol import (
    UserText,
    ToolCall,
    FunctionCallOutput,
    ApprovalDecisionEvt,
    UiMessageEvt,
)

from .state import (
    UiState,
    UserMessageItem,
    AssistantMarkdownItem,
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
    """
    # User message
    if isinstance(evt, UserText):
        return UiState(
            seq=state.seq + 1, items=[*state.items, UserMessageItem(text=evt.text)]
        )

    # Assistant markdown (from ui.send_message)
    if isinstance(evt, UiMessageEvt):
        md = evt.message.content if hasattr(evt, "message") else ""
        return UiState(
            seq=state.seq + 1, items=[*state.items, AssistantMarkdownItem(md=md)]
        )

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
        # For ui.send_message: do not create a ToolItem; UiMessageEvt after execution will surface AssistantMarkdown
        if evt.name == "mcp__ui__send_message":
            return state
        return start_tool(
            state, tool=evt.name, call_id=evt.call_id, cmd=cmd, args=parsed_args
        )

    # Approval decision → add to the current group
    if isinstance(evt, ApprovalDecisionEvt):
        kind = getattr(evt.decision, "kind", None)
        return update_tool_decision(state, evt.call_id, decision=kind)

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

        tool_name = None
        for it in reversed(state.items):
            if (
                getattr(it, "kind", None) == "Tool"
                and getattr(it, "call_id", None) == evt.call_id
            ):
                tool_name = getattr(it, "tool", None)
                break
        if isinstance(tool_name, str) and tool_name == "mcp__ui__send_message":
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
