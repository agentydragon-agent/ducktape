"""Adapters for converting ORM models to Pydantic wrappers.

Thin conversion layer between database ORM models and legacy Pydantic wrapper types
used by grader prompts.

Why this exists:
- ORM models use composite keys (snapshot_slug, tp_id)
- Pydantic wrappers use single namespaced IDs (e.g., "ducktape/2025-11-26-00/dead-code")
- Grader prompt builder expects Pydantic wrappers, dumps them to JSON

Future: Consider refactoring grader to use ORM directly or query via psql.
"""

from __future__ import annotations

from adgn.props.db.models import FalsePositive, TruePositive
from adgn.props.ids import FalsePositiveID, TruePositiveID
from adgn.props.rationale import Rationale
from adgn.props.snapshot_registry import KnownFalsePositive, TruePositiveIssue


def orm_to_wrapper_tps(tps: list[TruePositive]) -> list[TruePositiveIssue]:
    """Convert ORM TruePositive → TruePositiveIssue wrapper for grader.

    ORM model splits ID into composite key (snapshot_slug, tp_id).
    Wrapper uses just tp_id (issue slug) - snapshot context is implicit in structure.

    Occurrences work as-is: PydanticColumn already gives us list[TruePositiveOccurrence].
    """
    return [
        TruePositiveIssue(
            id=TruePositiveID(tp.tp_id),
            rationale=Rationale(tp.rationale),  # Validates 10-5000 char constraint
            occurrences=tp.occurrences,  # Already list[TruePositiveOccurrence] from PydanticColumn
        )
        for tp in tps
    ]


def orm_to_wrapper_fps(fps: list[FalsePositive]) -> list[KnownFalsePositive]:
    """Convert ORM FalsePositive → KnownFalsePositive wrapper for grader.

    ORM model splits ID into composite key (snapshot_slug, fp_id).
    Wrapper uses just fp_id (issue slug) - snapshot context is implicit in structure.

    Occurrences work as-is: PydanticColumn already gives us list[FalsePositiveOccurrence].
    """
    return [
        KnownFalsePositive(
            id=FalsePositiveID(fp.fp_id),
            rationale=Rationale(fp.rationale),
            occurrences=fp.occurrences,  # Already list[FalsePositiveOccurrence] from PydanticColumn
        )
        for fp in fps
    ]
