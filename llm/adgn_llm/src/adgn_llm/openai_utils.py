from __future__ import annotations

from enum import StrEnum


class ReasoningEffort(StrEnum):
    """String-valued helper mirroring the SDK's accepted reasoning-effort strings."""

    minimal = "minimal"
    low = "low"
    medium = "medium"
    high = "high"


def to_reasoning_effort(value: ReasoningEffort | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, ReasoningEffort):
        return value.value
    try:
        return ReasoningEffort(value).value
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ReasoningEffort)
        raise ValueError(f"Invalid reasoning effort {value!r}; expected one of: {allowed}") from exc


class ReasoningSummary(StrEnum):
    """Canonical values for Responses API reasoning summary selection."""

    auto = "auto"
    concise = "concise"
    detailed = "detailed"

