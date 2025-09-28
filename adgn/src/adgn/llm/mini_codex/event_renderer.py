from __future__ import annotations

from collections.abc import Callable
import json
import shlex
from typing import Any
from adgn.llm.openai_utils.model import ReasoningOut

from .aggregating_handler import BaseHandler
from .handler import AssistantText, ToolCall, ToolCallOutput, UserText
from .loop_control import NoLoopDecision
from .mcp_manager import parse_mcp_function

# Shared server/tool name constants
DOCKER_SERVER_NAME = "docker"
DOCKER_EXEC_TOOL_NAME = "docker_exec"


class DisplayEventsHandler(BaseHandler):
    """Handler that prints agent events directly (no separate renderer class).

    Configure by constructor args; omit this handler from the stack to suppress
    console output entirely.
    """

    def __init__(
        self,
        *,
        max_lines: int = 200,
        max_bytes: int = 8192,
        write: Callable[[str], None] = print,
    ) -> None:
        self._max_lines = max_lines
        self._max_bytes = max_bytes
        self._write = write
        self._calls: dict[str, ToolCall] = {}

    # Observer hooks ---------------------------------------------------------

    def on_user_text_event(self, evt: UserText) -> None:
        if evt.text:
            self._write(f"user:\n{self._truncate_text(evt.text)}")

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        if evt.text:
            self._write(f"assistant:\n{self._truncate_text(evt.text)}")

    def on_tool_call_event(self, evt: ToolCall) -> None:
        self._calls[evt.call_id] = evt
        # For docker_exec: render a concise bash-like input line here and skip JSON args
        try:
            server, tool = parse_mcp_function(evt.name or "")
        except Exception:
            server, tool = "", ""
        if (server, tool) == (DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME):
            call_args = _parse_json_or_none(evt.args_json) or {}
            if (
                isinstance(call_args, dict)
                and (cmd := call_args.get("cmd")) is not None
            ):
                cmd_line = (
                    shlex.join([str(x) for x in cmd])
                    if isinstance(cmd, list)
                    else str(cmd)
                )
                self._write(f"$ {cmd_line}")
            return
        s = self._render_tool_call(evt)
        if s:
            self._write(s)

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        c = self._calls.get(evt.call_id)
        s = self._render_tool_result(c, evt)
        if s:
            self._write(s)

    def on_reasoning(self, item: ReasoningOut) -> None:
        return None

    def on_before_sample(self) -> NoLoopDecision:
        return NoLoopDecision()

    # Rendering helpers ------------------------------------------------------

    def _render_tool_call(self, tc: ToolCall) -> str:
        name = tc.name or "<unknown>"
        parsed: Any | None = _parse_json_or_none(tc.args_json)
        args = (
            parsed
            if parsed is not None
            else ({"_raw": tc.args_json} if tc.args_json else {})
        )
        header = f"▶ {name} input:"
        return f"{header}\n{self._pp_json(args)}"

    def _render_tool_result(
        self,
        call: ToolCall | None,
        output: ToolCallOutput,
    ) -> str:
        result = output.result
        structured = result.structuredContent
        if structured is not None:
            data: Any = structured
        elif result.content:
            data = [block.model_dump(by_alias=True) for block in result.content]
        else:
            data = {"isError": result.isError}

        if call:
            try:
                server, tool = parse_mcp_function(call.name or "")
            except Exception:
                server, tool = "", ""
            if (server, tool) == (DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME):
                return self._render_docker_exec(call.name or "tool_output", call, data)

        return f"◀ {(call.name if call else 'tool_output')}:\n{self._pp_json(data)}"

    def _render_docker_exec(self, name: str, call: ToolCall, data: object) -> str:
        # Prefer structured keys when available; otherwise fall back to pretty JSON
        if not isinstance(data, dict):
            return f"$ <{name}>\n{self._pp_json(data)}"
        exit_code = data.get("exit_code")
        timed_out = data.get("timed_out")
        header_bits: list[str] = []
        if exit_code is not None:
            header_bits.append(f"exit {exit_code}")
        if timed_out:
            header_bits.append("timeout true")
        header = "[" + ", ".join(header_bits) + "]" if header_bits else ""

        out_parts: list[str] = []
        if header:
            out_parts.append(header)
        if stdout := data.get("stdout"):
            out_parts.append("stdout:")
            out_parts.append(self._truncate_text(_coerce_str(stdout)))
        if (stderr := data.get("stderr")) and stderr:
            out_parts.append("stderr:")
            out_parts.append(self._truncate_text(_coerce_str(stderr)))
        return "\n".join(out_parts)

    # Utility methods --------------------------------------------------------

    def _truncate_text(self, s: str) -> str:
        raw = s.encode("utf-8", errors="replace")
        if len(raw) > self._max_bytes:
            raw = raw[: self._max_bytes]
            s = raw.decode("utf-8", errors="replace")
            s += f"\n… truncated (+{len(s.encode('utf-8')) - len(raw)} bytes)"
        lines = s.splitlines()
        if len(lines) > self._max_lines:
            kept = lines[: self._max_lines]
            s = (
                "\n".join(kept)
                + f"\n… truncated (+{len(lines) - self._max_lines} lines)"
            )
        return s

    def _pp_json(self, obj: object) -> str:
        try:
            text = json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            text = str(obj)
        return self._truncate_text(text)


def _parse_json_or_none(s: str | None) -> Any | None:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _coerce_str(x: object) -> str:
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return str(x)
