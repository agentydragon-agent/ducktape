from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.paths import SpecimenRelativePath
from adgn.props.rationale import Rationale


class LineRange(BaseModel):
    start_line: int = Field(..., ge=1, description="1-based start line number")
    end_line: int | None = Field(
        default=None, description="1-based end line number (inclusive); omit for single-line anchor"
    )
    # TODO: Add optional per-range note/context field
    # Currently notes are only at occurrence level; per-range notes would help explain
    # why specific line ranges matter within a single occurrence (e.g., "definition site"
    # vs "call site" in the same occurrence)

    @model_validator(mode="after")
    def _validate_range(self) -> LineRange:
        if self.start_line < 1:
            raise ValueError("start_line must be >= 1")
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line when provided")
        return self

    def format(self) -> str:
        """Format line range as string (e.g., '123' or '123-145')."""
        if self.end_line is None:
            return str(self.start_line)
        return f"{self.start_line}-{self.end_line}"

    model_config = ConfigDict(extra="forbid")


class Occurrence(BaseModel):
    """One occurrence of a TruePositive.

    Authoring guidance:
    - A TruePositive represents one logical problem (id, rationale, properties). Use
      one TruePositive with multiple Occurrences when the same logical problem appears
      in several places but should be tracked together.
    - Prefer Occurrence-level notes for location-specific guidance; keep the
      TruePositive.rationale for the global explanation and acceptance criteria.
    """

    files: dict[SpecimenRelativePath, list[LineRange] | None] = Field(
        description=(
            "Maps file paths -> list of LineRanges within that file or `None` to indicate an unspecified anchor in the file. "
            + "One Occurrence may reference multiple files (e.g., multi-file code fragment) but represents a single logical location instance."
        )
    )
    note: str | None = Field(
        default=None,
        description=(
            "Occurrence-specific explanatory note, for details unique to this occurrence; "
            "do not repeat issue-level rationale here."
        ),
    )

    @field_serializer("files", when_used="json")
    def _serialize_files(self, value: dict[SpecimenRelativePath, list[LineRange] | None]) -> dict[str, Any]:
        """Convert Path keys to strings for JSON serialization."""
        return {str(k): v for k, v in value.items()}

    model_config = ConfigDict(extra="forbid")


class TruePositiveOccurrence(BaseModel):
    """One occurrence of a true positive.

    For true positives, each occurrence tracks minimal file sets required for detection.
    """

    files: dict[Path, list[LineRange] | None] = Field(
        description="Maps file paths to line ranges or None for unspecified anchor"
    )
    note: str | None = Field(default=None, description="Occurrence-specific note")
    expect_caught_from: set[frozenset[Path]] = Field(
        description=(
            "Minimal file sets for detection (AND/OR logic). "
            "Outer set = alternatives (OR), inner frozenset = required together (AND). "
            "Must be non-empty. "
            "\n\n"
            "Detection standard: 'If I gave a high-quality critic this file set to review, "
            "and they failed to find this issue, would that be a failure on their part?' "
            "A thorough code review starting from these files naturally includes following "
            "imports/calls, checking for existing patterns, and searching for duplication. "
            "Not 'can you detect this reading only these files in isolation'."
        )
    )

    @field_serializer("expect_caught_from")
    def serialize_expect_caught_from(self, value: set[frozenset[Path]]) -> list[list[str]]:
        """Convert set[frozenset[Path]] to JSON: list[list[str]]."""
        return [[str(p) for p in fs] for fs in value]

    @field_serializer("files", when_used="json")
    def _serialize_files(self, value: dict[Path, list[LineRange] | None]) -> dict[str, Any]:
        """Convert Path keys to strings for JSON serialization."""
        return {str(k): v for k, v in value.items()}

    @model_validator(mode="after")
    def validate_non_empty(self) -> TruePositiveOccurrence:
        if not self.expect_caught_from:
            raise ValueError("expect_caught_from must be non-empty")
        return self

    model_config = ConfigDict(extra="forbid")


class FalsePositiveOccurrence(BaseModel):
    """One occurrence of a false positive.

    For false positives, we track which files make this occurrence relevant.
    """

    files: dict[Path, list[LineRange] | None] = Field(
        description="Maps file paths to line ranges or None for unspecified anchor"
    )
    note: str | None = Field(default=None, description="Occurrence-specific note")
    relevant_files: set[Path] = Field(description="Files that make this FP relevant (ANY logic). Must be non-empty.")

    @field_serializer("relevant_files")
    def serialize_relevant_files(self, value: set[Path]) -> list[str]:
        """Convert set[Path] to JSON: list[str]."""
        return [str(p) for p in value]

    @field_serializer("files", when_used="json")
    def _serialize_files(self, value: dict[Path, list[LineRange] | None]) -> dict[str, Any]:
        """Convert Path keys to strings for JSON serialization."""
        return {str(k): v for k, v in value.items()}

    @model_validator(mode="after")
    def validate_non_empty(self) -> FalsePositiveOccurrence:
        if not self.relevant_files:
            raise ValueError("relevant_files must be non-empty")
        return self

    model_config = ConfigDict(extra="forbid")


class TruePositive(BaseModel):
    """True positive issue (post-migration).

    Represents a real problem that should be detected by critics.
    """

    tp_id: str = Field(description="Derived from filename by loader")
    snapshot_slug: SnapshotSlug = Field(description="From Jsonnet 'snapshot' field")
    rationale: Rationale
    occurrences: list[TruePositiveOccurrence]

    @model_validator(mode="after")
    def validate_multi_occurrence_notes(self) -> TruePositive:
        if len(self.occurrences) > 1:
            for occ in self.occurrences:
                if occ.note is None:
                    raise ValueError("note required for multi-occurrence true positives")
        return self

    model_config = ConfigDict(extra="forbid")


class FalsePositive(BaseModel):
    """False positive (post-migration).

    Represents a pattern that looks like an issue but isn't.
    """

    fp_id: str = Field(description="Derived from filename by loader")
    snapshot_slug: SnapshotSlug = Field(description="From Jsonnet 'snapshot' field")
    rationale: Rationale
    occurrences: list[FalsePositiveOccurrence]

    @model_validator(mode="after")
    def validate_multi_occurrence_notes(self) -> FalsePositive:
        if len(self.occurrences) > 1:
            for occ in self.occurrences:
                if occ.note is None:
                    raise ValueError("note required for multi-occurrence false positives")
        return self

    model_config = ConfigDict(extra="forbid")


class SnapshotIssuesLoadError(Exception):
    """Raised when per-issue Jsonnet evaluation/validation yields any errors in strict mode.

    Carries a list of human-readable error lines. __str__ joins them with newlines
    so pytest and CLIs surface a readable summary.
    """

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(str(self))

    def __str__(self) -> str:  # pragma: no cover - exercised via message rendering
        return "Snapshot issue loading errors:\n" + "\n".join(self.errors)


# Backwards compatibility alias (deprecated)
SpecimenIssuesLoadError = SnapshotIssuesLoadError


# Strongly-typed identifiers with validation
# BaseIssueID imported from ids module (validates no colons)


class IssueCore(BaseModel):
    """True positive metadata without occurrences.

    Minimal header describing a logical problem.
    When sending or storing per-location data separately, pair an IssueCore with
    one or more Occurrence objects rather than repeating metadata.
    """

    id: BaseIssueID
    rationale: Rationale

    model_config = ConfigDict(extra="forbid")


def should_catch_occurrence(occ: TruePositiveOccurrence, reviewed_files: set[Path]) -> bool:
    """Check if occurrence should be caught given reviewed files.

    Returns True if any alternative file set is a subset of reviewed files.
    """
    return any(alt.issubset(reviewed_files) for alt in occ.expect_caught_from)


def should_show_fp_occurrence(occ: FalsePositiveOccurrence, reviewed_files: set[Path]) -> bool:
    """Check if FP occurrence is relevant given reviewed files.

    Returns True if there's any overlap between relevant files and reviewed files.
    """
    return bool(occ.relevant_files & reviewed_files)
