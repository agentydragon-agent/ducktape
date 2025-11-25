"""OpenAI API pricing data.

Source: https://openai.com/api/pricing/
Last updated: 2025-11-24

All prices in $ per 1M tokens.
"""

from __future__ import annotations

# Pricing table: model name -> {input, cached_input, output} in $/1M tokens
# "-" in the source table means no cached pricing available
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.1": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "cached_input": 0.005, "output": 0.40},
    "gpt-5.1-chat-latest": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5-chat-latest": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5.1-codex": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5-codex": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5-pro": {"input": 15.00, "cached_input": 15.00, "output": 120.00},  # No cache discount
    "gpt-4.1": {"input": 2.00, "cached_input": 0.50, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "cached_input": 0.025, "output": 0.40},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
    "gpt-4o-2024-05-13": {"input": 5.00, "cached_input": 5.00, "output": 15.00},  # No cache discount
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "gpt-realtime": {"input": 4.00, "cached_input": 0.40, "output": 16.00},
    "gpt-realtime-mini": {"input": 0.60, "cached_input": 0.06, "output": 2.40},
    "gpt-4o-realtime-preview": {"input": 5.00, "cached_input": 2.50, "output": 20.00},
    "gpt-4o-mini-realtime-preview": {"input": 0.60, "cached_input": 0.30, "output": 2.40},
    "gpt-audio": {"input": 2.50, "cached_input": 2.50, "output": 10.00},  # No cache discount
    "gpt-audio-mini": {"input": 0.60, "cached_input": 0.60, "output": 2.40},  # No cache discount
    "gpt-4o-audio-preview": {"input": 2.50, "cached_input": 2.50, "output": 10.00},  # No cache discount
    "gpt-4o-mini-audio-preview": {"input": 0.15, "cached_input": 0.15, "output": 0.60},  # No cache discount
    "o1": {"input": 15.00, "cached_input": 7.50, "output": 60.00},
    "o1-pro": {"input": 150.00, "cached_input": 150.00, "output": 600.00},  # No cache discount
    "o3-pro": {"input": 20.00, "cached_input": 20.00, "output": 80.00},  # No cache discount
    "o3": {"input": 2.00, "cached_input": 0.50, "output": 8.00},
    "o3-deep-research": {"input": 10.00, "cached_input": 2.50, "output": 40.00},
    "o4-mini": {"input": 1.10, "cached_input": 0.275, "output": 4.40},
    "o4-mini-deep-research": {"input": 2.00, "cached_input": 0.50, "output": 8.00},
    "o3-mini": {"input": 1.10, "cached_input": 0.55, "output": 4.40},
    "o1-mini": {"input": 1.10, "cached_input": 0.55, "output": 4.40},
    "gpt-5.1-codex-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.00},
    "codex-mini-latest": {"input": 1.50, "cached_input": 0.375, "output": 6.00},
    "gpt-5-search-api": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-4o-mini-search-preview": {"input": 0.15, "cached_input": 0.15, "output": 0.60},  # No cache discount
    "gpt-4o-search-preview": {"input": 2.50, "cached_input": 2.50, "output": 10.00},  # No cache discount
    "computer-use-preview": {"input": 3.00, "cached_input": 3.00, "output": 12.00},  # No cache discount
    # Image models (no output pricing)
    "gpt-image-1": {"input": 5.00, "cached_input": 1.25, "output": 0.0},
    "gpt-image-1-mini": {"input": 2.00, "cached_input": 0.20, "output": 0.0},
}


# Default fallback pricing for unknown models
DEFAULT_PRICING = MODEL_PRICING["gpt-5"]
