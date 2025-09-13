from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn_llm.properties.models.issue import LineRange


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
