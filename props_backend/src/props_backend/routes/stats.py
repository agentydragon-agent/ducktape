"""Stats API routes for props dashboard."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from props.db.examples import count_available_examples_by_scope_all
from props.db.models import AgentDefinition, AgentRunStatus, RecallByDefinitionSplitKind
from props.db.session import get_session
from props.models.examples import ExampleKind
from props.splits import Split

router = APIRouter()


class SplitScopeStats(BaseModel):
    recall_pct: float | None
    lcb_pct: float | None
    n_examples: int
    zero_count: int
    status_counts: dict[AgentRunStatus, int]
    total_available: int


# Nested: split -> example_kind -> stats
SplitStats = dict[Split, dict[ExampleKind, SplitScopeStats]]


class DefinitionRow(BaseModel):
    definition_id: str
    created_at: datetime
    stats: SplitStats


class OverviewResponse(BaseModel):
    definitions: list[DefinitionRow]
    example_counts: dict[Split, dict[ExampleKind, int]]
    total_definitions: int


def to_stats(row: RecallByDefinitionSplitKind, total_available: int) -> SplitScopeStats:
    recall = row.recall_stats
    return SplitScopeStats(
        recall_pct=recall.mean * 100 if recall else None,
        lcb_pct=recall.lcb95 * 100 if recall and recall.lcb95 else None,
        n_examples=row.n_examples or 0,
        zero_count=row.zero_count or 0,
        status_counts=Counter(row.status_counts or {}),
        total_available=total_available,
    )


@router.get("/overview")
def get_overview() -> OverviewResponse:
    with get_session() as session:
        example_counts = count_available_examples_by_scope_all(session, [Split.TRAIN, Split.VALID])

        agg_results = (
            session.query(RecallByDefinitionSplitKind)
            .filter(RecallByDefinitionSplitKind.split.in_([Split.TRAIN, Split.VALID]))
            .all()
        )

        by_def: dict[str, dict[tuple[Split, ExampleKind], RecallByDefinitionSplitKind]] = defaultdict(dict)
        for row in agg_results:
            by_def[row.critic_definition_id][(row.split, row.example_kind)] = row

        metadata = {d.id: d for d in session.query(AgentDefinition).filter(AgentDefinition.id.in_(by_def.keys())).all()}

        sorted_ids = sorted(
            by_def.keys(), key=lambda d: metadata[d].created_at if d in metadata else datetime.min, reverse=True
        )[:100]

        def build_stats(def_id: str) -> SplitStats:
            result: SplitStats = defaultdict(dict)
            for (split, kind), row in by_def[def_id].items():
                result[split][kind] = to_stats(row, example_counts.get((split, kind), 0))
            return dict(result)

        rows = [
            DefinitionRow(
                definition_id=def_id,
                created_at=metadata[def_id].created_at if def_id in metadata else datetime.min,
                stats=build_stats(def_id),
            )
            for def_id in sorted_ids
        ]

        # Convert example_counts to nested dict
        nested_counts: dict[Split, dict[ExampleKind, int]] = defaultdict(dict)
        for (s, k), v in example_counts.items():
            nested_counts[s][k] = v

        return OverviewResponse(definitions=rows, example_counts=dict(nested_counts), total_definitions=len(sorted_ids))
