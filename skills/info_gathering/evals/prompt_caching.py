"""Prompt-caching Anthropic client for autogen evals.

autogen's AnthropicChatCompletionClient doesn't forward cache_control to the
Anthropic API. This module provides a subclass that injects cache_control
markers on the system message and the last conversation message.

See function_learning/debug/prompt_caching.md for the full investigation.
"""

import logging
from typing import Any

from autogen_ext.models.anthropic import AnthropicChatCompletionClient

logger = logging.getLogger(__name__)

_ANTHROPIC_MODEL_INFO: dict[str, Any] = {
    "vision": True,
    "function_calling": True,
    "json_output": True,
    "family": "unknown",
    "structured_output": True,
    "multiple_system_messages": False,
}

_CACHE_CONTROL = {"type": "ephemeral"}


class CachedAnthropicClient(AnthropicChatCompletionClient):
    """AnthropicChatCompletionClient with prompt caching enabled.

    Places cache_control on the system message AND the last conversation message.
    Haiku 4.5's minimum cacheable prefix is ~4096 tokens (not 1024 as documented).
    The system prompt alone (~1500 tokens) won't cache, but the growing conversation
    prefix caches from ~turn 5 onwards.
    """

    def __init__(self, *, model: str, **kwargs: Any) -> None:
        kwargs.setdefault("model_info", _ANTHROPIC_MODEL_INFO)
        super().__init__(model=model, **kwargs)
        self._wrap_messages_create()

    def _wrap_messages_create(self) -> None:
        raw_client = getattr(self, "_client", None)
        if raw_client is None:
            return
        original_create = raw_client.messages.create

        async def cached_create(
            *, model: str, messages: list[dict], max_tokens: int, system: Any = None, **rest: Any
        ) -> object:
            return await original_create(
                model=model,
                messages=_add_cache_to_last_message(messages),
                max_tokens=max_tokens,
                system=_add_cache_to_system(system),
                **rest,
            )

        raw_client.messages.create = cached_create


def _add_cache_to_system(system: Any) -> Any:
    """Convert system string to content block with cache_control."""
    if isinstance(system, str):
        return [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]
    return system


def _add_cache_to_last_message(messages: list[dict]) -> list[dict]:
    """Place cache_control on the last content block of the last message."""
    if not messages:
        return messages
    last_msg = messages[-1]
    if not isinstance(last_msg, dict):
        return messages
    content = last_msg.get("content")
    if isinstance(content, list) and content:
        last_block = content[-1]
        if isinstance(last_block, dict) and "cache_control" not in last_block:
            last_block["cache_control"] = _CACHE_CONTROL
    elif isinstance(content, str):
        last_msg["content"] = [{"type": "text", "text": content, "cache_control": _CACHE_CONTROL}]
    return messages
