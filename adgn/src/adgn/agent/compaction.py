"""Automatic transcript compaction handler for MiniCodex agents.

Monitors cumulative token usage and triggers compaction when approaching limits.
"""

from __future__ import annotations

import logging

from adgn.agent.events import Response
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Compact, LoopDecision, NoAction

logger = logging.getLogger(__name__)


class CompactionHandler(BaseHandler):
    """Automatically compact transcript when approaching token limits.

    Monitors cumulative token usage from API responses and returns a Compact
    decision when threshold is exceeded. Only triggers compaction once per session.
    """

    def __init__(self, threshold_tokens: int = 150_000, keep_recent_turns: int = 10):
        """Initialize compaction handler.

        Args:
            threshold_tokens: Token count threshold to trigger compaction (default 150k = 75% of 200k)
            keep_recent_turns: Number of recent transcript items to preserve (default 10)
        """
        self._threshold = threshold_tokens
        self._keep_recent = keep_recent_turns
        self._cumulative_tokens = 0
        self._compacted = False

    def on_response(self, evt: Response) -> None:
        """Track actual token usage from OpenAI API."""
        if evt.usage.total_tokens:
            self._cumulative_tokens += evt.usage.total_tokens
            logger.debug(
                "Token usage: %d/%d (%.1f%%)",
                self._cumulative_tokens,
                self._threshold,
                100 * self._cumulative_tokens / self._threshold,
            )

    def on_before_sample(self) -> LoopDecision:
        """Return Compact decision when threshold exceeded."""
        if self._cumulative_tokens > self._threshold and not self._compacted:
            logger.info(
                "Token threshold exceeded (%d > %d), triggering compaction", self._cumulative_tokens, self._threshold
            )
            self._compacted = True  # Only compact once per session
            return Compact(keep_recent_turns=self._keep_recent)

        return NoAction()  # Defer to other handlers
