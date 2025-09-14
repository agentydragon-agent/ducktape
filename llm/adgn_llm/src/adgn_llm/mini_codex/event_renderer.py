from __future__ import annotations

import json
import shlex
from typing import Callable

from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseReasoningItem,
)

from .agent import FunctionCallOutput
from .mcp_manager import parse_mcp_function  # constants below
from .aggregating_handler import BaseHandler
from .loop_control import NoLoopDecision

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
        self._calls: dict[str, ResponseFunctionToolCall] = {}

    # Observer hooks ---------------------------------------------------------

    def on_user_text(self, text: str) -> None:
        if text:
            self._write(f"user:\n{self._truncate_text(text)}")

    def on_assistant_text(self, text: str) -> None:
        if text:
            self._write(f"assistant:\n{self._truncate_text(text)}")

    def on_tool_call(self, call: ResponseFunctionToolCall) -> None:
        self._calls[call.call_id] = call
        # For docker_exec: render a concise bash-like input line here and skip JSON args
        try:
            server, tool = parse_mcp_function(call.name or "")
        except Exception:
            server, tool = "", ""
        if (server, tool) == (DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME):
            try:
                call_args = json.loads(call.arguments) if call.arguments else {}
            except Exception:
                call_args = {"_raw": call.arguments}
            if isinstance(call_args, dict) and (cmd := call_args.get("cmd")) is not None:
                if isinstance(cmd, list):
                    cmd_line = shlex.join([str(x) for x in cmd])
                else:
                    cmd_line = str(cmd)
                self._write(f"$ {cmd_line}")
            return
        s = self._render_tool_call(call)
        if s:
            self._write(s)

    def on_function_call_output(self, call: ResponseFunctionToolCall | None, output: FunctionCallOutput) -> None:
        c = call or self._calls.get(output.call_id)
        s = self._render_function_call_output(c, output)
        if s:
            self._write(s)

    def on_reasoning(self, item: ResponseReasoningItem) -> None:  # type: ignore[override]
        return None

    def on_before_sample(self) -> NoLoopDecision:  # type: ignore[override]
        return NoLoopDecision()

    # Rendering helpers ------------------------------------------------------

    def _render_tool_call(self, tc: ResponseFunctionToolCall) -> str:
        name = tc.name or "<unknown>"
        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except Exception:
            args = {"_raw": tc.arguments}
        header = f"▶ {name} input:"
        return f"{header}\n{self._pp_json(args)}"

    def _render_function_call_output(self, call: ResponseFunctionToolCall | None, output: FunctionCallOutput) -> str:
        # Try structured JSON; fall back to raw text
        try:
            data = json.loads(output.output)
        except Exception:
            return f"◀ tool_output (raw):\n{self._truncate_text(output.output)}"

        if call:
            # Prefer specialized docker_exec rendering when identifiable
            try:
                server, tool = parse_mcp_function(call.name or "")
            except Exception:
                server, tool = "", ""
            if (server, tool) == (DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME):
                return self._render_docker_exec(call.name or "tool_output", call, data)

        return f"◀ {(call.name if call else 'tool_output')}:\n{self._pp_json(data)}"

    def _render_docker_exec(self, name: str, call: ResponseFunctionToolCall, data: object) -> str:
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
        if stderr := data.get("stderr"):
            if stderr:
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
            s = "\n".join(kept) + f"\n… truncated (+{len(lines) - self._max_lines} lines)"
        return s

    def _pp_json(self, obj: object) -> str:
        try:
            text = json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            text = str(obj)
        return self._truncate_text(text)


def _coerce_str(x: object) -> str:
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return str(x)
