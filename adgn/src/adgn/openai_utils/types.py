from __future__ import annotations

from enum import Enum, StrEnum
from typing import Literal, cast

from typing_extensions import TypedDict


def to_reasoning_effort(value: ReasoningEffort | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, ReasoningEffort):
        return cast(str, value.value)
    try:
        effort = ReasoningEffort(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ReasoningEffort)
        raise ValueError(
            f"Invalid reasoning effort {value!r}; expected one of: {allowed}",
        ) from exc
    return cast(str, effort.value)


class ReasoningEffort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


ReasoningEffortLiteral = Literal["low", "medium", "high"]


class ReasoningParams(TypedDict, total=False):
    effort: ReasoningEffortLiteral
    summary: str


def build_reasoning_params(
    effort: ReasoningEffort | str | None,
    summary: ReasoningSummary | str | None = None,
) -> ReasoningParams | None:
    """Convert optional reasoning knobs into adapter ReasoningParams."""

    effort_value = to_reasoning_effort(effort)
    summary_value: str | None
    if summary is None:
        summary_value = None
    elif isinstance(summary, ReasoningSummary):
        summary_value = summary.value
    else:
        summary_value = ReasoningSummary(summary).value

    if effort_value is None and summary_value is None:
        return None

    payload: dict[str, str] = {}
    if effort_value is not None:
        payload["effort"] = cast(ReasoningEffortLiteral, effort_value)
    if summary_value is not None:
        payload["summary"] = summary_value

    return cast(ReasoningParams, payload)


class ReasoningSummary(StrEnum):
    """Canonical values for Responses API reasoning summary selection."""

    auto = "auto"
    concise = "concise"
    detailed = "detailed"
