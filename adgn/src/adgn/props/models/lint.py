from __future__ import annotations

from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adgn.props.models.issue import LineRange


class Correction(BaseModel):
    file: str
    range: LineRange

    model_config = ConfigDict(extra="forbid")


class PropertyIncorrectlyAssigned(BaseModel):
    kind: Literal["PROPERTY_INCORRECTLY_ASSIGNED"] = "PROPERTY_INCORRECTLY_ASSIGNED"
    property: str

    model_config = ConfigDict(extra="forbid")


class PropertyShouldBeAssigned(BaseModel):
    kind: Literal["PROPERTY_SHOULD_BE_ASSIGNED"] = "PROPERTY_SHOULD_BE_ASSIGNED"
    property: str

    model_config = ConfigDict(extra="forbid")


class AnchorIncorrect(BaseModel):
    kind: Literal["ANCHOR_INCORRECT"] = "ANCHOR_INCORRECT"
    correction: Correction

    model_config = ConfigDict(extra="forbid")


class FalsePositive(BaseModel):
    kind: Literal["FALSE_POSITIVE"] = "FALSE_POSITIVE"

    model_config = ConfigDict(extra="forbid")


class TruePositive(BaseModel):
    kind: Literal["TRUE_POSITIVE"] = "TRUE_POSITIVE"

    model_config = ConfigDict(extra="forbid")


class OtherError(BaseModel):
    kind: Literal["OTHER_ERROR"] = "OTHER_ERROR"
    description: str

    model_config = ConfigDict(extra="forbid")


# Rationale-focused annotations
class RationaleError(BaseModel):
    kind: Literal["RATIONALE_ERROR"] = "RATIONALE_ERROR"
    error_description: str

    model_config = ConfigDict(extra="forbid")


class RationaleImprovement(BaseModel):
    kind: Literal["RATIONALE_IMPROVEMENT"] = "RATIONALE_IMPROVEMENT"
    suggested_improvement: str

    model_config = ConfigDict(extra="forbid")


IssueLintFinding = Annotated[
    PropertyIncorrectlyAssigned
    | PropertyShouldBeAssigned
    | AnchorIncorrect
    | FalsePositive
    | TruePositive
    | OtherError
    | RationaleError
    | RationaleImprovement,
    Field(discriminator="kind"),
]


class IssueLintFindingRecord(BaseModel):
    finding: IssueLintFinding
    rationale: str | None = None

    model_config = ConfigDict(extra="forbid")


class LintSubmitPayload(BaseModel):
    """Final linter result payload."""

    model_config = ConfigDict(extra="forbid")

    message_md: str = Field(..., description="Concise Markdown report; do not restate pass/fail.")
    suggested_rationale: str | None = Field(
        default=None,
        description=(
            "If non-null, corrected Issue rationale text suggested by linter, based on the actual evidence "
            "(e.g., remove mentions of nonexistent callers and prescribe deleting dead code). Null means keep original."
        ),
    )
    findings: list[IssueLintFindingRecord] = Field(description="Lint findings.")

    @model_validator(mode="after")
    def _validate_tp_fp_one_of(self) -> LintSubmitPayload:
        """Ensure either exactly one TRUE_POSITIVE or FALSE_POSITIVE, or (no TP/FP and >=1 OTHER_ERROR)."""
        # Count by inner finding kinds (not the record wrapper)
        type_counter = Counter(type(fr.finding) for fr in self.findings)
        if type_counter[TruePositive] == 0 and type_counter[FalsePositive] == 1:
            return self
        if type_counter[TruePositive] == 1 and type_counter[FalsePositive] == 0:
            return self
        if type_counter[OtherError] == 0:
            raise ValueError(
                "Findings must have: (a) exactly one false positive or true positive finding, or (b) at least 1 'other error' finding"
            )
        return self


# ChecklistItem (commented out — checklist handling is currently disabled)
# class ChecklistItem(BaseModel):
#     """Hierarchical checklist for the agent's performed checks.
#
#     May be per-property or general. Answer should be "YES"/"NO" when binary; free strings allowed when necessary.
#     """
#
#     item: str = Field(..., description="Checklist question or assertion")
#     subitems: list["ChecklistItem"] = Field(
#         default_factory=list, description="Nested checks under this item"
#     )
#     log: str = Field(default="", description="Short log of evidence or steps taken")
#     answer: bool | str = Field(
#         ...,
#         description="Answer; use boolean for binary (true/false); free text allowed when needed",
#     )
# checklist: list[ChecklistItem] | None = Field(
#     default=None,
#     description="Root checklist items (tree) summarizing checks performed (per-property or general)",
# )
