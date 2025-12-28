"""Critic data models.

Pydantic models and dataclasses for the critic subsystem.
Extracted to avoid circular dependencies with prompts.util.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from props_core.ids import BaseIssueID
from props_core.models.true_positive import Occurrence
from props_core.rationale import Rationale
from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# File Scope Types and Constants
# =============================================================================

type ResolvedFileScope = set[Path]
"""Resolved file scope - guaranteed to be an explicit set of paths (no sentinels). Internal only."""


# =============================================================================
# Critic Submit Models (used by prompts/)
# =============================================================================


class ReportedIssue(BaseModel):
    """Candidate issue reported by the critic (flattened header).

    Exposes only id and rationale; internal-only fields like should_flag are not part of the critic schema.

    Note: occurrences may be empty while the critique is being built incrementally; the submit tool enforces ≥1.
    """

    id: BaseIssueID
    rationale: Rationale
    occurrences: list[Occurrence] = Field(description="Issue occurrences")

    model_config = ConfigDict(extra="forbid")


class CriticSubmitPayload(BaseModel):
    """Structured critic output."""

    issues: list[ReportedIssue] = Field(description="Issues found")
    notes_md: str | None = Field(
        description="Optional Markdown note. Only for info not represented in structured form in `issues`."
    )
    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Critic Output Models
# =============================================================================


class CriticSuccess(BaseModel):
    """Successful critic output."""

    tag: Literal["success"] = "success"
    result: CriticSubmitPayload = Field(description="Successful critique with issues and optional notes")

    model_config = ConfigDict(frozen=True)


class CriticMaxTurnsExceeded(BaseModel):
    """Critic ran out of turns before completing."""

    tag: Literal["max_turns_exceeded"] = "max_turns_exceeded"
    max_turns: int = Field(description="Maximum turns that were allowed", gt=0)

    model_config = ConfigDict(frozen=True)


class CriticContextLengthExceeded(BaseModel):
    """Critic input exceeded model's context window."""

    tag: Literal["context_length_exceeded"] = "context_length_exceeded"
    error_message: str = Field(description="Error message from the API")

    model_config = ConfigDict(frozen=True)


class CriticReportedFailure(BaseModel):
    """Critic explicitly reported it cannot complete."""

    tag: Literal["reported_failure"] = "reported_failure"
    reason: str = Field(description="Reason provided by the critic for inability to complete")

    model_config = ConfigDict(frozen=True)


CriticOutput = Annotated[
    CriticSuccess | CriticMaxTurnsExceeded | CriticContextLengthExceeded | CriticReportedFailure,
    Field(
        discriminator="tag",
        description="Critic output: success, max turns exceeded, context length exceeded, or reported failure",
    ),
]
"""Discriminated union of critic outcomes."""
