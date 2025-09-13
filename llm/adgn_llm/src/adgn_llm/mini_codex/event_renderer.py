from __future__ import annotations

import json
import shlex
from typing import Callable, Sequence

from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
)

from .agent import FunctionCallOutput
from .loop_control import BaseLoopController, LoopController
from .mcp_manager import parse_mcp_function  # constants below
from .aggregating_handler import BaseHandler, NoLoopDecision

# Shared server/tool name constants
DOCKER_SERVER_NAME = "docker"
DOCKER_EXEC_TOOL_NAME = "docker_exec"


__all__ = [
    "ConsoleEventRenderer",
    "NullConsoleEventRenderer",
    "DisplayEventsMixin",
    "PrettyPrintController",
]


# TODO(mpokorny): Refactor event rendering to a composable, multi-handler design.
# - Prefer composition over mixin; decouple formatting from emission
# - Allow multiple sinks (console, JSONL, rich UI) via a handler registry
# - Keep ConsoleEventRenderer as one handler; provide a Null handler explicitly
# - Controllers should accept list[EventHandler] rather than a single renderer
# - Remove private _render_* coupling from DisplayEventsMixin
class ConsoleEventRenderer:
    """Pretty renderer for OpenAI ResponseOutput items (handles printing itself).

    Usage:
      - Construct once with desired options and a write callable (defaults to print)
      - Call emit_* methods to print human-readable traces
      - render_* methods remain available for text assembly when needed
    """

    def __init__(
        self,
        *,
        max_lines: int = 200,
        max_bytes: int = 8192,
        show_text: bool = False,
        write: Callable[[str], None] = print,
    ) -> None:
        self._max_lines = max_lines
        self._max_bytes = max_bytes
        self._show_text = show_text
        self._write = write

    # High-level API ---------------------------------------------------------

    def render_outputs(self, items: Sequence["OutputItem"]) -> str:
        parts: list[str] = []
        for item in items:
            if isinstance(item, ResponseFunctionToolCall):
                parts.append(self._render_tool_call(item))
            elif isinstance(item, ResponseOutputMessage):
                if self._show_text:
                    msg = self._render_message(item)
                    if msg:
                        parts.append(msg)
            elif isinstance(item, FunctionCallOutput):
                parts.append(self._render_function_call_output(item))
            else:
                # Other output kinds (reasoning etc.) are omitted by default
                # to keep console succinct.
                continue
        return "\n".join(p for p in parts if p)

    def emit_outputs(
        self,
        items: Sequence["OutputItem"],
        *,
        write: Callable[[str], None] = print,
    ) -> None:
        text = self.render_outputs(items)
        if text:
            write(text)

    def render_pair(self, call: ResponseFunctionToolCall, output: FunctionCallOutput) -> str:
        name = call.name or ""
        try:
            data = json.loads(output.output)
        except Exception:
            data = output.output
        try:
            server, tool = parse_mcp_function(name)
        except Exception:
            server, tool = "", ""
        if server == DOCKER_SERVER_NAME and tool == DOCKER_EXEC_TOOL_NAME:
            return self._render_docker_exec(name, call, data)
        return f"◀ {name or 'tool_output'}:\n{self._pp_json(data)}"

    # Emitters ---------------------------------------------------------------
    def emit_user_text(self, text: str) -> None:
        if self._show_text:
            self._write(f"user:\n{self._truncate_text(text)}")

    def emit_assistant_text(self, text: str) -> None:
        if self._show_text:
            self._write(f"assistant:\n{self._truncate_text(text)}")

    def emit_tool_call(self, tc: ResponseFunctionToolCall) -> None:
        s = self._render_tool_call(tc)
        if s:
            self._write(s)

    def emit_function_call_output(self, call: ResponseFunctionToolCall | None, output: FunctionCallOutput) -> None:
        if call is None:
            s = self._render_tool_output_generic(output)
        else:
            s = self.render_pair(call, output)
        if s:
            self._write(s)

    # Renderers --------------------------------------------------------------

    def _render_tool_call(self, tc: ResponseFunctionToolCall) -> str:
        name = tc.name or "<unknown>"
        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except Exception:
            args = {"_raw": tc.arguments}
        header = f"▶ {name} input:"
        return f"{header}\n{self._pp_json(args)}"

    def _render_message(self, msg: ResponseOutputMessage) -> str:
        parts = [p.text for p in msg.content if isinstance(p, ResponseOutputText) and p.text]
        if not parts:
            return ""
        text = "\n".join(parts)
        text = self._truncate_text(text)
        return f"assistant:\n{text}"

    def _render_tool_output_generic(self, fco: FunctionCallOutput) -> str:
        try:
            data = json.loads(fco.output)
        except Exception:
            return f"◀ tool_output (raw):\n{self._truncate_text(fco.output)}"
        return f"◀ tool_output:\n{self._pp_json(data)}"

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
        # Reconstruct shell-ish line when possible
        try:
            call_args = json.loads(call.arguments) if call.arguments else {}
        except Exception:
            call_args = {"_raw": call.arguments}
        if isinstance(call_args, dict) and (cmd := call_args.get("cmd")) is not None:
            if isinstance(cmd, list):
                cmd_line = shlex.join([str(x) for x in cmd])
            else:
                cmd_line = str(cmd)
            out_parts.append(f"$ {cmd_line}")
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

    # Helpers ----------------------------------------------------------------

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


# Unified output item type used in this module for type hints
OutputItem = ResponseFunctionToolCall | ResponseOutputMessage | ResponseReasoningItem | FunctionCallOutput


class NullConsoleEventRenderer(ConsoleEventRenderer):
    """Renderer that suppresses all human-readable console output."""

    def __init__(self) -> None:
        super().__init__(show_text=False)

    def render_outputs(self, items: Sequence["OutputItem"]) -> str:  # type: ignore[override]
        return ""

    def emit_outputs(self, items: Sequence["OutputItem"], *, write: Callable[[str], None] = print) -> None:  # type: ignore[override]
        return None

    def render_pair(self, call: ResponseFunctionToolCall, output: FunctionCallOutput) -> str:  # type: ignore[override]
        return ""

    def _render_tool_call(self, tc: ResponseFunctionToolCall) -> str:  # type: ignore[override]
        return ""

    def _render_message(self, msg: ResponseOutputMessage) -> str:  # type: ignore[override]
        return ""

    def _render_function_call_output(self, fco: FunctionCallOutput) -> str:  # type: ignore[override]
        return ""


class DisplayEventsHandler(BaseHandler):
    """Standalone handler that pretty-prints agent events using a ConsoleEventRenderer.

    Observer-only: on_before_sample returns NoLoopDecision() to explicitly defer.
    """

    def __init__(
        self,
        *,
        renderer: ConsoleEventRenderer | None = None,
        show_text: bool = False,
        write: Callable[[str], None] = print,
    ) -> None:
        self._renderer = renderer or ConsoleEventRenderer(show_text=show_text, write=write)
        self._calls: dict[str, ResponseFunctionToolCall] = {}

    def on_user_text(self, text: str) -> None:
        self._renderer.emit_user_text(text)

    def on_assistant_text(self, text: str) -> None:
        self._renderer.emit_assistant_text(text)

    def on_tool_call(self, call: ResponseFunctionToolCall) -> None:
        self._calls[call.call_id] = call
        self._renderer.emit_tool_call(call)

    def on_function_call_output(self, call: ResponseFunctionToolCall | None, output: FunctionCallOutput) -> None:
        c = call or self._calls.get(output.call_id)
        self._renderer.emit_function_call_output(c, output)

    def on_reasoning(self, item: ResponseReasoningItem) -> None:
        return None

    def on_before_sample(self) -> NoLoopDecision:
        return NoLoopDecision()


class DisplayEventsMixin(BaseLoopController):
    """Mixin base that pretty-prints agent events using a renderer that does the printing."""

    def __init__(
        self,
        *,
        renderer: ConsoleEventRenderer | None = None,
        show_text: bool = False,
        write: Callable[[str], None] = print,
    ) -> None:
        # If no renderer provided, create one with the desired text setting and writer
        self._renderer = renderer or ConsoleEventRenderer(show_text=show_text, write=write)
        self._calls: dict[str, ResponseFunctionToolCall] = {}

    # Event hooks used by MiniCodex -------------------------------------------------
    def on_user_text(self, text: str) -> None:  # type: ignore[override]
        self._renderer.emit_user_text(text)

    def on_assistant_text(self, text: str) -> None:  # type: ignore[override]
        self._renderer.emit_assistant_text(text)

    def on_tool_call(self, call: ResponseFunctionToolCall) -> None:  # type: ignore[override]
        self._calls[call.call_id] = call
        self._renderer.emit_tool_call(call)

    def on_function_call_output(self, call: ResponseFunctionToolCall, output: FunctionCallOutput) -> None:  # type: ignore[override]
        c = call or self._calls.get(output.call_id)
        self._renderer.emit_function_call_output(c, output)

    def on_reasoning(self, item: ResponseReasoningItem) -> None:  # type: ignore[override]
        return None


class PrettyPrintController(BaseHandler):
    """Wrapper controller that delegates decisions to an inner controller.

    Keeps the old PrettyPrintController API but now leverages DisplayEventsMixin
    for rendering; this reduces layering elsewhere.
    """

    def __init__(
        self,
        inner: LoopController,
        *,
        renderer: ConsoleEventRenderer | None = None,
        show_text: bool = False,
        write: Callable[[str], None] = print,
    ) -> None:
        # Keep signature for backward compatibility but do not perform rendering here.
        # Rendering is handled by DisplayEventsHandler registered separately.
        self._inner = inner

    def on_before_sample(self):  # type: ignore[override]
        # Delegate decision to wrapped inner controller (migrated behavior preserved).
        return self._inner.on_before_sample()
