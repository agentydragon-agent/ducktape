from __future__ import annotations

from typing import Any

from time import monotonic
from itertools import cycle

from rich.console import Console
from rich.text import Text

from .aggregating_handler import BaseHandler, NoLoopDecision


class OneLineProgressHandler(BaseHandler):
    """Minimal one-line progress handler.

    Displays a single-line status with a spinner, number of tool calls, and a brief
    last action. Non-blocking: updates are printed inline using carriage return.

    Usage: register as a handler in MiniCodex.create(..., handlers=[AutoHandler(), OneLineProgressHandler()])
    """

    def __init__(self, *, console: Console | None = None) -> None:
        self.console = console or Console()
        self._tool_calls = 0
        self._last_action = "(idle)"
        self._spinner = cycle(["-", "\\", "|", "/"])  # simple spinner
        # Track last render time to avoid noisy updates; allow manual forcing via _render()
        self._last_render = 0.0

    # --- observer hooks (fast, non-blocking) ---
    def on_tool_call(self, call: Any) -> None:
        self._tool_calls += 1
        self._last_action = f"tool:{getattr(call, 'name', str(call))}"
        self._render()

    def on_function_call_output(self, call: Any, output: Any) -> None:
        # call may be None if not available; prefer output.call_id
        cid = getattr(output, "call_id", None) or getattr(call, "call_id", "")
        self._last_action = f"fco:{cid}"
        self._render()

    def on_assistant_text(self, text: str) -> None:
        # Keep last assistant snippet short
        excerpt = text.strip().replace("\n", " ")[:40]
        self._last_action = f"assistant:{excerpt}"
        self._render()

    def on_user_text(self, text: str) -> None:
        self._last_action = "user"
        self._render()

    def on_reasoning(self, item: Any) -> None:
        self._last_action = "reasoning"
        self._render()

    def on_before_sample(self):
        # Observer-only hook must explicitly defer
        return NoLoopDecision()

    # --- rendering ---
    def _render(self, force: bool = False) -> None:
        # Throttle updates to ~20Hz to avoid noisy consoles
        now = monotonic()
        if not force and now - self._last_render < 0.05:
            return
        self._last_render = now
        s = next(self._spinner)
        txt = Text(f"{s} tools={self._tool_calls} last={self._last_action}")
        # Print without newline and flush; rely on carriage return
        try:
            self.console.print(txt, end="\r")
        except Exception:
            # Fallback: write to stderr raw
            import sys

            sys.stderr.write(txt.plain + "\r")
            sys.stderr.flush()
