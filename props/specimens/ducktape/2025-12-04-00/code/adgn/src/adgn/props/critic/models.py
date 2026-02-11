"""Critic data models.

Pydantic models and dataclasses for the critic subsystem.
Extracted to avoid circular dependencies with prompts.util.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.models.true_positive import Occurrence
from adgn.props.rationale import Rationale

# =============================================================================
# File Scope Types and Constants
# =============================================================================

ALL_FILES_WITH_ISSUES: Literal["all"] = "all"
"""Sentinel value: scope critic to all files with ground truth TP/FP issues."""

type FileScopeSpec = set[Path] | Literal["all"]
"""File scope specification - either explicit file set or ALL_FILES_WITH_ISSUES sentinel.
Requires resolution via resolve_critic_scope() to produce ResolvedFileScope."""

type ResolvedFileScope = set[Path]
"""Resolved file scope - guaranteed to be an explicit set of paths (no sentinels)."""


# =============================================================================
# Critic Input/Output Models
# =============================================================================


class CriticInput(BaseModel):
    """Input for a critic run (codebase → candidate issues).

    Files can be specified as:
    - ALL_FILES_WITH_ISSUES sentinel: resolved to files with ground truth TP/FP issues
    - Explicit set[Path]: specific files to review

    Resolution happens inside run_critic().
    """

    snapshot_slug: SnapshotSlug = Field(description="Snapshot slug (e.g., ducktape/2025-11-26-00)")
    files: FileScopeSpec = Field(
        description=f'Files to review: explicit set or "{ALL_FILES_WITH_ISSUES}" sentinel for ground truth files'
    )
    prompt_sha256: str = Field(description="SHA256 hash of the system prompt for reproducibility tracking")
    prompt_optimization_run_id: UUID | None = Field(
        default=None, description="Optional link to prompt optimization session"
    )

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
    occurrences: list[Occurrence] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CriticSubmitPayload(BaseModel):
    """Structured critic output."""

    issues: list[ReportedIssue] = Field(default_factory=list, description="Issues found")
    notes_md: str | None = Field(
        default=None,
        description="Optional Markdown note. Only for info not represented in structured form in `issues`.",
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
