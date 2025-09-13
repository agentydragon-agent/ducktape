from __future__ import annotations

import warnings
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adgn_llm.properties.prop_utils import PropertyID, validate_property_ids


def _warn_deprecated_model(message: str) -> None:
    """Emit a standardized deprecation warning for legacy protocol models."""
    warnings.warn(message, DeprecationWarning, stacklevel=2)


class LineRange(BaseModel):
    start_line: int = Field(..., description="1-based start line number")
    end_line: int | None = Field(
        default=None,
        description="1-based end line number (inclusive); omit for single-line anchor",
    )

    @model_validator(mode="after")
    def _validate_range(self) -> "LineRange":
        if self.start_line < 1:
            raise ValueError("start_line must be >= 1")
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line when provided")
        return self


class Occurrence(BaseModel):
    """A single occurrence/location of an Issue.

    - `files` maps file paths -> either a list of LineRange objects (one or more
      ranges within that file) or `None` to indicate an unspecified anchor in the
      file. A single Occurrence may reference multiple files (e.g., a multi-file
      code fragment) but represents a single logical location instance.
    - `note` is an optional, occurrence-level explanatory string. Use it for
      brief, local context (what to change or why this instance matters). Do not
      duplicate the Issue.rationale here.

    Authoring guidance (single source of truth):
    - An Issue represents one logical problem (id, rationale, properties). Use
      one Issue with multiple Occurrences when the same logical problem appears
      in several places but should be tracked together.
    - Prefer Occurrence-level notes for location-specific guidance; keep the
      Issue.rationale for the global explanation and acceptance criteria.
    """

    files: dict[str, list[LineRange] | None]
    note: str | None = Field(
        default=None,
        description=(
            "Occurrence-specific note. Use for details unique to this occurrence; "
            "do not repeat the issue-level rationale here."
        ),
    )


class SpecimenIssuesLoadError(Exception):
    """Raised when per-issue Jsonnet evaluation/validation yields any errors in strict mode.

    Carries a list of human-readable error lines. __str__ joins them with newlines
    so pytest and CLIs surface a readable summary.
    """

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(str(self))

    def __str__(self) -> str:  # pragma: no cover - exercised via message rendering
        return "Specimen issue loading errors:\n" + "\n".join(self.errors)


class Issue(BaseModel):
    """Issue (legacy) — metadata coupled with its occurrences.

    NOTE: This model is deprecated in favor of IssueCore (metadata) + separate
    Occurrence objects, but remains supported for backward compatibility.

    Semantics (single-source of truth):
    - An Issue represents one logical problem (the "what" and "why").
    - It can have multiple occurrences (instances) where that problem appears.
      Each Occurrence describes the specific file(s)/line ranges and optional
      occurrence-level note describing local context or suggested edits.

    When to use which shape:
    - Use I.issueOneOccurrence when the issue is a single logical change that
      must be applied atomically across multiple files (delete wrapper + update
      caller together).
    - Use I.issueOccurrencesFromLines to record multiple independent
      manifestations of the same issue that can be fixed separately.

    Examples (punchy):

    1) "1 issue, 2 occurrences" — independent fixes (Pydantic/JSON form)
       JSON example:
       {
         "id": "iss-trailing-whitespace",
         "should_flag": true,
         "rationale": "Trailing whitespace in tests",
         "properties": ["no-dead-code"],
         "instances": [
           { "files": { "tests/a.py": [ { "start_line": 10 } ] } },
           { "files": { "tests/b.py": [ { "start_line": 20 } ] } }
         ]
       }

    2) "1 occurrence, 2 locations" — one atomic fix across files (Pydantic/JSON form)
       JSON example:
       {
         "id": "iss-remove-wrapper",
         "should_flag": true,
         "rationale": "Remove deprecated wrapper and update its sole caller",
         "properties": ["no-oneoff-vars-and-trivial-wrappers"],
         "instances": [
           {
             "files": {
               "pkg/wrapper.py": [ { "start_line": 12, "end_line": 20 } ],
               "pkg/caller.py":  [ { "start_line": 45, "end_line": 52 } ]
             }
           }
         ]
       }

    Keep the Issue.rationale as the authoritative explanation; occurrence
    notes should be short and local.
    """

    id: str
    should_flag: bool = True
    rationale: str
    properties: list[PropertyID] = []
    gap_note: str | None = Field(
        None,
        description="Freeform description of aspects of this issue that need better coverage in formal properties. These may also include higher-level or messier heuristics. Issue rationale should be freestanding - without expecting that gap_note will be read by the reader.",
    )

    model_config = ConfigDict(extra="forbid")
    instances: list[Occurrence]

    def model_post_init(self, _: Any) -> None:  # type: ignore[override]
        _warn_deprecated_model(
            "Issue is deprecated: use IssueCore + Occurrence(s). This model will be removed after migration."
        )

    @model_validator(mode="after")
    def _validate_self(self) -> "Issue":
        validate_property_ids(self.properties)
        if not self.instances:
            raise ValueError("`instances` must contain at least one occurrence")
        return self

    @property
    def files_touched(self) -> set[str]:
        paths: set[str] = set()
        for occ in self.instances or []:
            paths.update(occ.files.keys())
        return paths


class IssueCore(BaseModel):
    """Issue metadata without occurrences.

    The canonical, minimal header describing a logical problem. When sending or
    storing per-location data separately, pair an IssueCore with one or more
    Occurrence objects rather than repeating metadata.

    - Use IssueCore for APIs or tooling that pass around a single occurrence
      together with metadata (e.g., lint-issue flows).
    - Prefer not to duplicate IssueCore fields across multiple files; instead
      reference a single Issue (id) and attach Occurrence(s) describing locations.
    """

    id: str
    should_flag: bool
    rationale: str
    properties: list[PropertyID] = []
    gap_note: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_self(self) -> "IssueCore":
        validate_property_ids(self.properties)
        return self

    @classmethod
    def from_issue(cls, issue: "Issue") -> "IssueCore":
        return cls(
            id=issue.id,
            should_flag=issue.should_flag,
            rationale=issue.rationale,
            properties=list(issue.properties),
            gap_note=issue.gap_note,
        )
