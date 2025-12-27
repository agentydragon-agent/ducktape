"""Stats API routes for props dashboard."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from props.agent_types import AgentType
from props.db.examples import count_available_examples_by_scope_all
from props.db.models import AgentDefinition, AgentRunStatus, RecallByDefinitionSplitKind
from props.db.session import get_session
from props.models.examples import ExampleKind
from props.splits import Split

router = APIRouter()


class DefinitionInfo(BaseModel):
    id: str
    agent_type: AgentType
    created_at: datetime


class DefinitionsResponse(BaseModel):
    definitions: list[DefinitionInfo]


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

        # Get ALL critic definitions, not just those with stats
        all_definitions = (
            session.query(AgentDefinition)
            .filter(AgentDefinition.agent_type == AgentType.CRITIC)
            .order_by(AgentDefinition.created_at.desc())
            .limit(100)
            .all()
        )

        agg_results = (
            session.query(RecallByDefinitionSplitKind)
            .filter(RecallByDefinitionSplitKind.split.in_([Split.TRAIN, Split.VALID]))
            .all()
        )

        by_def: dict[str, dict[tuple[Split, ExampleKind], RecallByDefinitionSplitKind]] = defaultdict(dict)
        for row in agg_results:
            by_def[row.critic_definition_id][(row.split, row.example_kind)] = row

        def build_stats(def_id: str) -> SplitStats:
            result: SplitStats = defaultdict(dict)
            if def_id in by_def:
                for (split, kind), row in by_def[def_id].items():
                    result[split][kind] = to_stats(row, example_counts.get((split, kind), 0))
            return dict(result)

        rows = [
            DefinitionRow(definition_id=d.id, created_at=d.created_at, stats=build_stats(d.id)) for d in all_definitions
        ]

        # Convert example_counts to nested dict
        nested_counts: dict[Split, dict[ExampleKind, int]] = defaultdict(dict)
        for (s, k), v in example_counts.items():
            nested_counts[s][k] = v

        return OverviewResponse(definitions=rows, example_counts=dict(nested_counts), total_definitions=len(rows))


@router.get("/definitions")
def list_definitions(agent_type: AgentType | None = None) -> DefinitionsResponse:
    """List all agent definitions, optionally filtered by type."""
    with get_session() as session:
        query = session.query(AgentDefinition)
        if agent_type:
            query = query.filter_by(agent_type=agent_type)
        definitions = query.order_by(AgentDefinition.created_at.desc()).all()
        return DefinitionsResponse(
            definitions=[
                DefinitionInfo(id=d.id, agent_type=AgentType(d.agent_type), created_at=d.created_at)
                for d in definitions
            ]
        )
