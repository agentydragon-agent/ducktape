from __future__ import annotations

from enum import StrEnum

# Re-export the official OpenAI SDK enum for reasoning effort
from openai.types.shared_params import ReasoningEffort


class ReasoningSummary(StrEnum):
    """Canonical values for Responses API reasoning summary selection.

    Keep in sync with OpenAI Responses API docs.
    """

    auto = "auto"
    concise = "concise"
    detailed = "detailed"


__all__ = ["ReasoningEffort", "ReasoningSummary"]
