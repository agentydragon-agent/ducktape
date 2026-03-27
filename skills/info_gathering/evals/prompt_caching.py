"""Prompt caching helper for Anthropic models via autogen.

autogen's AnthropicChatCompletionClient doesn't forward cache_control to the
Anthropic API. This module provides a monkey-patch that injects cache_control
markers on the system message and the last conversation message.

See function_learning/debug/prompt_caching.md for the full investigation.
"""

import logging

from autogen_core.models import ChatCompletionClient

logger = logging.getLogger(__name__)


def enable_prompt_caching(client: ChatCompletionClient) -> None:
    """Monkey-patch an AnthropicChatCompletionClient to enable prompt caching.

    Places cache_control on the system message AND the last conversation message.
    Haiku 4.5's minimum cacheable prefix is ~4096 tokens (not 1024 as documented).
    The system prompt alone (~1500 tokens) won't cache, but the growing conversation
    prefix caches from ~turn 5 onwards.
    """
    raw_client = getattr(client, "_client", None)
    if raw_client is None:
        return
    original_create = raw_client.messages.create

    async def cached_create(**kwargs: object) -> object:
        # Convert system string to content block with cache_control.
        system = kwargs.get("system")
        if isinstance(system, str):
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

        # Place cache_control on the last message in the conversation.
        messages = kwargs.get("messages")
        if isinstance(messages, list) and messages:
            last_msg = messages[-1]
            if isinstance(last_msg, dict):
                content = last_msg.get("content")
                if isinstance(content, list) and content:
                    last_block = content[-1]
                    if isinstance(last_block, dict) and "cache_control" not in last_block:
                        last_block["cache_control"] = {"type": "ephemeral"}
                elif isinstance(content, str):
                    last_msg["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]

        return await original_create(**kwargs)

    raw_client.messages.create = cached_create
