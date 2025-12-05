"""Internal Pydantic models for sync operations.

⚠️⚠️⚠️ PRIVATE MODULE - DO NOT IMPORT OUTSIDE db/sync/ ⚠️⚠️⚠️

These are intermediate representations used during Jsonnet → ORM conversion.
For runtime access, use ORM models from db.models.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...ids import SnapshotSlug
from ...models.true_positive import FalsePositiveOccurrence, TruePositiveOccurrence
from ...rationale import Rationale


class TruePositive(BaseModel):
    """True positive issue (Pydantic, for sync only).

    Represents a real problem that should be detected by critics.
    Intermediate representation between Jsonnet and ORM.
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
    """False positive (Pydantic, for sync only).

    Represents a pattern that looks like an issue but isn't.
    Intermediate representation between Jsonnet and ORM.
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
