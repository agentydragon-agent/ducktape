"""Cost calculation utilities for OpenAI API usage."""

from __future__ import annotations

import logging

from adgn.agent.events import GroundTruthUsage
from adgn.openai_utils.model_metadata import get_model_metadata

logger = logging.getLogger(__name__)


def calculate_cost(usage: GroundTruthUsage) -> float:
    """Calculate cost in dollars from usage.

    Handles cached tokens and reasoning tokens when available.

    Raises:
        KeyError: If model pricing is not available
    """
    meta = get_model_metadata(usage.model)

    cost = 0.0

    # Input tokens (accounting for cached if available)
    if usage.input_tokens:
        if usage.input_tokens_details and usage.input_tokens_details.cached_tokens:
            cached = usage.input_tokens_details.cached_tokens
            regular = usage.input_tokens - cached
            cost += (regular / 1_000_000) * meta.input_usd_per_1m_tokens
            cost += (cached / 1_000_000) * meta.cached_input_usd_per_1m_tokens
        else:
            cost += (usage.input_tokens / 1_000_000) * meta.input_usd_per_1m_tokens

    # Output tokens
    if usage.output_tokens:
        cost += (usage.output_tokens / 1_000_000) * meta.output_usd_per_1m_tokens

    # Reasoning tokens are already included in output_tokens for o-series

    return cost
