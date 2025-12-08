"""Critic scope models for per-file training examples.

A CriticScope defines a focused training example: which files to review together
as a single unit. Multiple scopes per snapshot allow more granular training signal.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel

# Sentinel value for "all files with issues" (for backwards compatibility)
ALL_FILES_WITH_ISSUES: Literal["all"] = "all"
"""Sentinel value: scope critic to all files with ground truth TP/FP issues."""


class ExplicitFileScope(OpenAIStrictModeBaseModel):
    """Explicit list of files to review.

    Used when targeting specific files rather than all files with issues.
    """

    kind: Literal["explicit"] = "explicit"
    files: list[str] = Field(description="Explicit file paths to review")
    # list not set: OpenAI strict mode doesn't accept uniqueItems in JSON schemas
    # str not Path: OpenAI strict mode doesn't accept format="path" in JSON schemas


class AllFilesScope(OpenAIStrictModeBaseModel):
    """Review all files with ground truth issues.

    This sentinel expands to all files that have TP or FP annotations.
    """

    kind: Literal["all"] = "all"


CriticScopeSpec = Annotated[ExplicitFileScope | AllFilesScope, Field(discriminator="kind")]
"""Critic scope specification - discriminated union for OpenAI strict mode.

Two variants:
- ExplicitFileScope: Explicit file list
- AllFilesScope: All files with issues (sentinel)

NOTE: This is the API format. Internally we may convert to set[Path] after resolution.
"""


class CriticScope(BaseModel):
    """A single critic scope: files to review together.

    Defines one training example for a snapshot.
    Rationale for groupings should be documented via YAML comments.
    """

    files: CriticScopeSpec = Field(description="Files to review: explicit list or 'all' sentinel")

    model_config = ConfigDict(frozen=True, extra="forbid")


__all__ = ["ALL_FILES_WITH_ISSUES", "AllFilesScope", "CriticScope", "CriticScopeSpec", "ExplicitFileScope"]
