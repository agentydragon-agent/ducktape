"""Pydantic models for YAML issue file parsing.

⚠️⚠️⚠️ PRIVATE MODULE - DO NOT IMPORT OUTSIDE db/sync/ ⚠️⚠️⚠️

These models provide a permissive input layer for YAML parsing with flexible location shapes.
They normalize and validate YAML data, then expand to canonical TruePositive/FalsePositive models.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...ids import SnapshotSlug
from ...models.true_positive import FalsePositiveOccurrence, LineRange, TruePositiveOccurrence
from ...rationale import Rationale
from ._models import FalsePositive, TruePositive


class YAMLOccurrence(BaseModel):
    """Permissive input model for YAML occurrences - accepts multiple location shapes.

    Supports flexible line specifications:
    - Single line: 42 → normalized to [[42, 42]]
    - Line range: [10, 20] → normalized to [[10, 20]]
    - Multiple ranges: [[10, 15], [20, 25]] → kept as-is
    - No specific lines: null → kept as None

    After field validation, files dict contains list[list[int]] or None values.
    """

    occurrence_id: str = Field(description="Unique ID within issue (e.g., 'occ-0', 'occ-1')")
    # Type annotation is post-validation (normalize_files converts flexible input to canonical form)
    files: dict[str, list[list[int]] | None] = Field(
        description="File paths to line specifications (normalized to list of [start, end] ranges)"
    )
    note: str | None = Field(default=None, description="Occurrence-specific explanation")
    expect_caught_from: list[list[str]] | None = Field(
        default=None, description="Minimal file sets for TP detection (TPs only)"
    )
    relevant_files: list[str] | None = Field(default=None, description="Files making this FP relevant (FPs only)")
    only_matchable_from_files: list[str] | None = Field(
        default=None,
        description=(
            "GRADING OPTIMIZATION: Restricts which critique outputs can match this occurrence. "
            "If set, a critique reporting issues only in files OUTSIDE this set will be skipped "
            "during matching (assumed non-match without semantic comparison). "
            "NULL = allow matching from any file (conservative default). "
            "Non-empty = skip matching if critique's files don't overlap. "
            "Independent of expect_caught_from (detection source ≠ valid reporting targets)."
        ),
    )

    @field_validator("only_matchable_from_files", mode="before")
    @classmethod
    def validate_only_matchable_from_files(cls, v: list[str] | None) -> list[str] | None:
        """Reject empty list - must be null or non-empty."""
        if v is not None and len(v) == 0:
            raise ValueError("only_matchable_from_files must be null or non-empty (got empty list)")
        return v

    @field_validator("files", mode="before")
    @classmethod
    def normalize_files(cls, v: dict) -> dict[str, list[list[int]] | None]:
        """Convert flexible line specs to canonical list[list[int]] form.

        Input shapes:
          42 → [[42, 42]]
          [10, 20] → [[10, 20]]
          [[10, 15], [20, 25]] → [[10, 15], [20, 25]]
          null → null

        Returns dict with normalized values (list[list[int]] or None).
        """
        normalized: dict[str, list[list[int]] | None] = {}
        for file_path, spec in v.items():
            if spec is None:
                # No specific lines: keep as None
                normalized[file_path] = None
            elif isinstance(spec, int):
                # Single line: 42 → [[42, 42]]
                normalized[file_path] = [[spec, spec]]
            elif isinstance(spec, list):
                if not spec:
                    raise ValueError(f"Empty list not allowed for {file_path} (use null for no lines)")
                if all(isinstance(x, int) for x in spec):
                    # Range: [10, 20] → [[10, 20]]
                    if len(spec) != 2:
                        raise ValueError(f"Line range for {file_path} must have exactly 2 elements, got {len(spec)}")
                    normalized[file_path] = [spec]
                elif all(isinstance(x, list) for x in spec):
                    # Already multiple ranges: [[10, 15], [20, 25]]
                    # Validate each range
                    for r in spec:
                        if not all(isinstance(x, int) for x in r):
                            raise ValueError(f"Invalid range in {file_path}: {r} (must be list of ints)")
                        if len(r) != 2:
                            raise ValueError(f"Range in {file_path} must have 2 elements, got {len(r)}: {r}")
                    normalized[file_path] = spec
                else:
                    raise ValueError(
                        f"Mixed types in line spec for {file_path}: {spec} "
                        "(must be all ints for range or all lists for multiple ranges)"
                    )
            else:
                raise ValueError(
                    f"Invalid line spec for {file_path}: {spec} (type: {type(spec).__name__}). "
                    "Expected int, [start, end], [[r1_start, r1_end], ...], or null"
                )
        return normalized

    def _build_files_dict(self) -> dict[Path, list[LineRange] | None]:
        """Convert normalized files to Path keys and LineRange values."""
        files_dict: dict[Path, list[LineRange] | None] = {}
        for file_str, ranges_val in self.files.items():
            if ranges_val is None:
                files_dict[Path(file_str)] = None
            else:
                files_dict[Path(file_str)] = [LineRange(start_line=r[0], end_line=r[1]) for r in ranges_val]
        return files_dict

    def to_tp_occurrence(self) -> TruePositiveOccurrence:
        """Expand to canonical TruePositiveOccurrence."""
        if self.expect_caught_from is None:
            raise ValueError("expect_caught_from required for TP occurrence (should be auto-inferred by validator)")

        return TruePositiveOccurrence(
            occurrence_id=self.occurrence_id,
            files=self._build_files_dict(),
            note=self.note,
            expect_caught_from={frozenset(Path(p) for p in trigger_set) for trigger_set in self.expect_caught_from},
            only_matchable_from_files={Path(p) for p in self.only_matchable_from_files}
            if self.only_matchable_from_files
            else None,
        )

    def to_fp_occurrence(self) -> FalsePositiveOccurrence:
        """Expand to canonical FalsePositiveOccurrence."""
        if self.relevant_files is None:
            raise ValueError("relevant_files required for FP occurrence (should be auto-inferred by validator)")

        return FalsePositiveOccurrence(
            occurrence_id=self.occurrence_id,
            files=self._build_files_dict(),
            note=self.note,
            relevant_files={Path(p) for p in self.relevant_files},
            only_matchable_from_files={Path(p) for p in self.only_matchable_from_files}
            if self.only_matchable_from_files
            else None,
        )

    model_config = ConfigDict(extra="forbid")


class YAMLIssue(BaseModel):
    """Top-level YAML issue model - permissive input with validation.

    Enforces business rules:
    - Multi-occurrence issues must have notes on all occurrences
    - Single-file TPs can omit expect_caught_from (auto-inferred)
    - Multi-file TPs must have explicit expect_caught_from
    - FPs can omit relevant_files (auto-inferred from files keys)
    """

    rationale: str = Field(description="Full explanation of the issue")
    should_flag: bool = Field(description="True for TP, False for FP")
    occurrences: list[YAMLOccurrence] = Field(description="Issue occurrences")

    @model_validator(mode="after")
    def validate_multi_occurrence_notes(self) -> YAMLIssue:
        """Enforce note requirement for multi-occurrence issues."""
        if len(self.occurrences) > 1:
            for occ in self.occurrences:
                if occ.note is None:
                    raise ValueError(
                        f"Occurrence {occ.occurrence_id} missing required note "
                        "(multi-occurrence issues must have notes on all occurrences)"
                    )
        return self

    @model_validator(mode="after")
    def auto_infer_expect_caught_from(self) -> YAMLIssue:
        """Auto-infer expect_caught_from for single-file TPs."""
        if self.should_flag:
            for occ in self.occurrences:
                if occ.expect_caught_from is None:
                    files = list(occ.files.keys())
                    if len(files) == 1:
                        # Auto-infer: single file → [[that_file]]
                        occ.expect_caught_from = [[files[0]]]
                    else:
                        raise ValueError(
                            f"Multi-file TP occurrence {occ.occurrence_id} requires "
                            f"explicit expect_caught_from (found files: {files})"
                        )
        return self

    @model_validator(mode="after")
    def validate_fp_relevant_files(self) -> YAMLIssue:
        """Ensure FPs have relevant_files set (can auto-infer from files)."""
        if not self.should_flag:
            for occ in self.occurrences:
                if occ.relevant_files is None:
                    # Auto-infer from files keys
                    occ.relevant_files = list(occ.files.keys())
        return self

    def to_true_positive(self, tp_id: str, snapshot_slug: SnapshotSlug) -> TruePositive:
        """Expand to canonical TruePositive model."""
        if not self.should_flag:
            raise ValueError("Cannot convert FP (should_flag=false) to TruePositive")

        return TruePositive(
            tp_id=tp_id,
            snapshot_slug=snapshot_slug,
            rationale=Rationale(self.rationale),
            occurrences=[occ.to_tp_occurrence() for occ in self.occurrences],
        )

    def to_false_positive(self, fp_id: str, snapshot_slug: SnapshotSlug) -> FalsePositive:
        """Expand to canonical FalsePositive model."""
        if self.should_flag:
            raise ValueError("Cannot convert TP (should_flag=true) to FalsePositive")

        return FalsePositive(
            fp_id=fp_id,
            snapshot_slug=snapshot_slug,
            rationale=Rationale(self.rationale),
            occurrences=[occ.to_fp_occurrence() for occ in self.occurrences],
        )

    model_config = ConfigDict(extra="forbid")
