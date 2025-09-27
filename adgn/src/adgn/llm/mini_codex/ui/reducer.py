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
        stdout = stderr = None
        exit_code = None
        parsed_out: dict | None = None
        try:
            out = json.loads(evt.output)
            parsed_out = out if isinstance(out, dict) else None
            if parsed_out:
                stdout = parsed_out.get("stdout_text") or parsed_out.get("stdout")
                stderr = parsed_out.get("stderr_text") or parsed_out.get("stderr")
                exit_code = parsed_out.get("exit_code")
        except Exception:
            parsed_out = None
        # Prefer updating exec-style if present; else update JSON-style output
        next_state = update_tool_exec_stream(
            state, evt.call_id, stdout=stdout, stderr=stderr, exit_code=exit_code
        )
        if next_state is state:
            # Locate tool to decide how to handle JSON output
            tool_name = None
            for it in reversed(state.items):
                if (
                    getattr(it, "kind", None) == "Tool"
                    and getattr(it, "call_id", None) == evt.call_id
                ):
                    tool_name = getattr(it, "tool", None)
                    break
            # For ui.send_message: do NOT attach JSON output; UiMessageEvt will surface as AssistantMarkdown
            if isinstance(tool_name, str) and tool_name == "mcp__ui__send_message":
                return state
            return update_tool_json_output(state, evt.call_id, output=parsed_out)
        return next_state

    # Unknown event → no-op
    return state
