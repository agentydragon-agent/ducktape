"""Critic scope models for per-file training examples.

A CriticScope defines a focused training example: which files to review together
as a single unit. Multiple scopes per snapshot allow more granular training signal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Sentinel value for "all files with issues"
ALL_FILES_WITH_ISSUES: Literal["all"] = "all"
"""Sentinel value: scope critic to all files with ground truth TP/FP issues."""

type CriticScopeSpec = set[Path] | Literal["all"]
"""Critic scope specification - either explicit file set or ALL_FILES_WITH_ISSUES sentinel."""


class CriticScope(BaseModel):
    """A single critic scope: files to review together.

    Defines one training example for a snapshot. Files can be:
    - Explicit set of Path objects
    - "all" sentinel for all files with issues

    Rationale for grouping should be documented via YAML comments.
    """

    files: CriticScopeSpec = Field(description="Files to review: explicit set or 'all' sentinel")

    model_config = ConfigDict(frozen=True, extra="forbid")


__all__ = ["ALL_FILES_WITH_ISSUES", "CriticScope", "CriticScopeSpec"]
