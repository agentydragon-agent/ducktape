"""Critic data models.

Pydantic models and dataclasses for the critic subsystem.
Extracted to avoid circular dependencies with prompts.util.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.models.critic_scopes import CriticScopeSpec
from adgn.props.models.true_positive import Occurrence
from adgn.props.rationale import Rationale

# =============================================================================
# File Scope Types and Constants
# =============================================================================

type ResolvedFileScope = set[Path]
"""Resolved file scope - guaranteed to be an explicit set of paths (no sentinels). Internal only."""


# =============================================================================
# Critic Input/Output Models
# =============================================================================


class CriticInput(BaseModel):
    """Input for a critic run (codebase → candidate issues).

    Internal format used by critic execution (after MCP tool converts from CriticFilesInput).
    """

    snapshot_slug: SnapshotSlug = Field(description="Snapshot slug (e.g., ducktape/2025-11-26-00)")
    files: CriticScopeSpec = Field(description="Files to review")
    prompt_sha256: str = Field(description="SHA256 hash of the system prompt for reproducibility tracking")

    model_config = ConfigDict(extra="forbid")


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


CriticOutput = Annotated[
    CriticSuccess | CriticMaxTurnsExceeded | CriticContextLengthExceeded,
    Field(discriminator="tag", description="Critic output: success, max turns exceeded, or context length exceeded"),
]
"""Discriminated union of critic outcomes: success, max_turns_exceeded, or context_length_exceeded."""
