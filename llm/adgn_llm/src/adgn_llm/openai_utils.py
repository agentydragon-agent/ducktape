from __future__ import annotations

from enum import StrEnum

# Re-export the official OpenAI SDK alias (typing.Literal) for type annotations
from openai.types.shared_params import ReasoningEffort


class ReasoningEffort(StrEnum):
    """String-valued enum for CLI/options while remaining str-compatible.

    Values mirror OpenAI's ReasoningEffort (typing.Literal), so instances can be
    passed directly to the OpenAI SDK (StrEnum is a str subclass).
    """

    minimal = "minimal"
    low = "low"
    medium = "medium"
    high = "high"


class ReasoningSummary(StrEnum):
    """Canonical values for Responses API reasoning summary selection."""

    auto = "auto"
    concise = "concise"
    detailed = "detailed"

