from __future__ import annotations


from pydantic import BaseModel

from adgn.llm.mini_codex.handler import (
    BaseHandler,
    BeforeToolCallDecision,
    ContinueDecision,
    ToolCall,
)
from adgn.llm.mini_codex.loop_control import Continue, Abort, RequireAny
from adgn.llm.mini_codex.ui.shared_bus import UiBus


class UiAutoHandler(BaseModel, BaseHandler):
    """Combine tool-required loop control with bus-driven end_turn (no name parsing)."""

    bus: UiBus

    def on_before_sample(self):
        if self.bus.consume_end_turn():
            return Abort()
        # Always require tool use; agent must produce UI via ui.send_message and end via ui.end_turn
        return Continue(RequireAny())

    async def before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        # No per-tool interception needed; end-turn is handled via BUS in on_before_sample
        return ContinueDecision()
