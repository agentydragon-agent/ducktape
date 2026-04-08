"""Replay chat client for deterministic testing.

Returns pre-scripted ChatResponse objects in order, replacing AutoGen's
ReplayChatCompletionClient for the Agent Framework migration.
"""

from collections.abc import Sequence

from agent_framework import ChatResponse


class ReplayChatClient:
    """Chat client that replays scripted responses in order.

    Implements the same get_response interface as Agent Framework chat clients
    but returns pre-configured responses instead of calling an LLM.
    """

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def get_response(self, messages: Sequence, **kwargs: object) -> ChatResponse:
        if self._index >= len(self._responses):
            raise RuntimeError(f"ReplayChatClient exhausted: used all {len(self._responses)} responses")
        response = self._responses[self._index]
        self._index += 1
        return response
