"""Cost calculation utilities for OpenAI API usage."""

from __future__ import annotations

import logging

from adgn.agent.handler import GroundTruthUsage
from adgn.openai_utils.pricing import MODEL_PRICING

logger = logging.getLogger(__name__)


def calculate_cost(usage: GroundTruthUsage) -> float:
    """Calculate cost in dollars from usage.

    Handles cached tokens and reasoning tokens when available.

    Raises:
        ValueError: If model pricing is not available
    """
    pricing = MODEL_PRICING.get(usage.model)
    if pricing is None:
        raise ValueError(
            f"No pricing information for model: {usage.model}. "
            f"Available models: {', '.join(sorted(MODEL_PRICING.keys()))}"
        )

    cost = 0.0

    # Input tokens (accounting for cached if available)
    if usage.input_tokens:
        if usage.input_tokens_details and usage.input_tokens_details.cached_tokens:
            cached = usage.input_tokens_details.cached_tokens
            regular = usage.input_tokens - cached
            cost += (regular / 1_000_000) * pricing["input"]
            cost += (cached / 1_000_000) * pricing["cached_input"]
        else:
            cost += (usage.input_tokens / 1_000_000) * pricing["input"]

    # Output tokens
    if usage.output_tokens:
        cost += (usage.output_tokens / 1_000_000) * pricing["output"]

    # Reasoning tokens are already included in output_tokens for o-series

    return cost
