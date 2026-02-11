from __future__ import annotations

from typing import Final

# Canonical map of model id to context window tokens. Extend as needed.
# TODO(mpokorny): Populate with real values for all models we use;
#                 verify against provider docs and update heuristics if needed.
MODEL_CONTEXT_TOKENS: Final[dict[str, int]] = {
    # OpenAI families (examples; adjust to your usage)
    "gpt-5": 128_000,
    "gpt-4.1": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "o4-mini": 128_000,
    "o3": 128_000,
    # Fallbacks for custom aliases you may use in configs
    "default": 128_000,
}


def context_window_tokens_by_id(model_id: str | None) -> int:
    if not model_id:
        return MODEL_CONTEXT_TOKENS["default"]
    # Exact match first
    if model_id in MODEL_CONTEXT_TOKENS:
        return MODEL_CONTEXT_TOKENS[model_id]
    # Case-insensitive fallbacks by family prefix
    lower = model_id.lower()
    if lower.startswith("gpt-5"):
        return 128_000
    if lower.startswith("gpt-4.1"):
        return 128_000
    if lower.startswith("gpt-4o"):
        return 128_000
    if lower.startswith("o3"):
        return 128_000
    if lower.startswith("o4-mini"):
        return 128_000
    return MODEL_CONTEXT_TOKENS["default"]
