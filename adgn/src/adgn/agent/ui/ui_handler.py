from __future__ import annotations

from pydantic import BaseModel
from typing import Callable

from adgn.agent.reducer import format_notifications_message
from adgn.agent.handler import (
    BaseHandler,
    BeforeToolCallDecision,
    ContinueDecision,
    ToolCall,
)
from adgn.agent.loop_control import Continue, Abort, RequireAny
from adgn.agent.ui.shared_bus import UiBus

# Import just the NotificationsBatch type - it's a lightweight Pydantic model
from adgn.agent.mcp_manager import NotificationsBatch


class UiModeHandler(BaseModel, BaseHandler):
    """UI mode handler combining notifications delivery and RequireAny policy.

    Single handler that:
    1. Checks for end_turn signal and aborts if set
    2. Delivers any pending MCP notifications as system messages
    3. Enforces RequireAny tool policy for UI interaction
    """

    bus: UiBus
    poll_notifications: Callable[
        [], NotificationsBatch
    ]  # Light dependency - just a function

    def on_before_sample(self):
        # First check end_turn
        if self.bus.consume_end_turn():
            return Abort()

        # Check for and deliver notifications using shared logic
        batch = self.poll_notifications()
        msg = format_notifications_message(batch)

        if msg is not None:
            # Return Continue with RequireAny policy AND the notification message
            return Continue(RequireAny(), inserts_input=(msg,))

        # No notifications - just require tool use
        return Continue(RequireAny())

    async def before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        # No per-tool interception needed; end-turn is handled via BUS in on_before_sample
        return ContinueDecision()
