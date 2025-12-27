"""Agent definition performance statistics for targeted mode.

In targeted mode, validation includes both per-file and full-snapshot examples.
The examples table IS accessible (filenames only - no ground truth or traces).
All performance metrics are queried via views directly.

IMPORTANT: This module is ONLY compatible with targeted mode. In whole-repo mode,
the occurrence_credits view is RLS-blocked for VALID split. Use
definition_stats_whole_repo.py instead.

Functions:
- show_comprehensive_stats(): Display definition overview with LCB-based ranking
- show_train_vs_valid(): Compare train vs validation performance
- show_top_definitions(): Show top-performing definitions on validation

Key views used:
- occurrence_credits: Per-occurrence recall credits (TRAIN split only in whole-repo mode)
- aggregated_recall_by_definition: Pre-aggregated stats with n_examples, ucb, lcb

NOTE: This example references query builders that were never implemented. The functions
are stubbed to allow import but will raise NotImplementedError if called.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from rich.console import Console

from props.cli.cmd_stats import STATS_TABLE_LEGEND, _STATUS_COLUMNS
from props.db.session import get_session
from props.db.models import RecallByDefinitionSplitKind
from props.display import ColumnDef, build_table_from_schema, fmt_pct
from props.models.examples import ExampleKind
from props.splits import Split


# Stub types - these were never implemented in query_builders
class SplitPerformanceStats(BaseModel):
    """Stub type for split performance statistics."""

    mean_recall: float = 0.0
    lcb: float | None = None
    total_count: int = 0
    zero_count: int = 0
    stuck_count: int = 0
    context_count: int = 0


def query_definition_performance_stats(session: Any, limit: int = 50) -> list[Any]:
    """Stub - query builder was never implemented."""
    raise NotImplementedError(
        "query_definition_performance_stats was never implemented. "
        "Use RecallByDefinitionSplitKind ORM model directly."
    )




def _format_split_stats(stats) -> str:
    """Format split statistics as: recall% lcb% (N) Zz Ss Cc"""
    if stats is None:
        return "—"
    lcb_str = f"{stats.lcb:.1%}" if stats.lcb is not None else "—"
    return (
        f"{stats.mean_recall:.1%} "
        f"lcb:{lcb_str} "
        f"({stats.total_count}) "
        f"{stats.zero_count}z "
        f"{stats.stuck_count}s "
        f"{stats.context_count}c"
    )


def _build_performance_columns() -> list[ColumnDef[Any, Any]]:
    """Build column definitions for combined train/valid performance table."""
    return [
        ColumnDef("Split", lambda r: r.split, width=6),
        ColumnDef("Definition", lambda r: r.critic_definition_id, width=20),
        ColumnDef("Model", lambda r: r.critic_model[:12], width=15),
        ColumnDef("Scope", lambda r: r.example_kind, width=18),
        ColumnDef("N", lambda r: r.n_examples, str, justify="right", width=5),
        ColumnDef("Runs", lambda r: r.n_runs, str, justify="right", width=5),
        ColumnDef("Recall", lambda r: r.occurrences_caught_stats.mean if r.occurrences_caught_stats else None, fmt_pct, justify="right", width=7),
        ColumnDef("UCB", lambda r: r.occurrences_caught_stats.ucb95 if r.occurrences_caught_stats else None, fmt_pct, justify="right", width=7),
        ColumnDef("LCB", lambda r: r.occurrences_caught_stats.lcb95 if r.occurrences_caught_stats else None, fmt_pct, justify="right", width=7),
        *_STATUS_COLUMNS,
        ColumnDef("", lambda r: " ⚠️" if r.split == Split.VALID and r.n_examples < 5 else "", width=3),
    ]


class _ExpandedStatsRow(BaseModel):
    """Row for expanded stats display (one row per definition/split/example_kind)."""

    critic_definition_id: str
    created_at: datetime
    split: Split
    example_kind: ExampleKind
    stats: SplitPerformanceStats


def show_comprehensive_stats(console: Console, limit: int = 50) -> None:
    """Display comprehensive definition statistics across splits and example kinds.

    Shows for each (definition, split, example_kind) combination:
    - Created timestamp
    - Split and scope kind
    - Performance metrics: mean recall, LCB, success/total counts, zero%, stuck%, context%

    Definitions are sorted by creation date (most recent first).

    Args:
        console: Rich console for output.
        limit: Maximum number of definitions to display.
    """

    with get_session() as session:
        results = query_definition_performance_stats(session, limit=limit)

        # Expand rows: one per (definition, split, example_kind)
        expanded_rows: list[_ExpandedStatsRow] = []
        for row in results:
            for (split, example_kind), stats in row.stats.items():
                expanded_rows.append(
                    _ExpandedStatsRow(
                        critic_definition_id=row.critic_definition_id,
                        created_at=row.created_at,
                        split=split,
                        example_kind=example_kind,
                        stats=stats,
                    )
                )

        console.print(
            f"\n[bold]Definition Performance Overview ({len(results)} definitions, "
            f"{len(expanded_rows)} rows by split/scope)[/bold]"
        )

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Definition", lambda r: r.critic_definition_id, width=20),
            ColumnDef("Created", lambda r: r.created_at.strftime("%m-%d %H:%M"), width=12),
            ColumnDef("Split", lambda r: r.split.value, width=6),
            ColumnDef("Scope", lambda r: r.example_kind.value[:15], width=16),
            ColumnDef("Stats", lambda r: _format_split_stats(r.stats), width=45),
        ]

        console.print(build_table_from_schema(expanded_rows, columns))

        console.print()
        console.print("Format: recall% lcb:X% (N) Zz Ss Cc")
        console.print(STATS_TABLE_LEGEND)


def show_train_vs_valid(console: Console, limit: int = 40) -> None:
    """Display train vs validation performance comparison for targeted mode.

    In targeted mode, both per-file and full-snapshot examples are visible for
    validation. Query uses aggregated_recall_by_definition view directly.

    IMPORTANT: Check n_examples >= 5 before trusting validation metrics.
    Small sample sizes have high variance.

    Args:
        console: Rich console for output.
        limit: Maximum number of rows to display.
    """

    with get_session() as session:
        results = (
            session.query(RecallByDefinitionSplitKind)
            .filter(RecallByDefinitionSplitKind.split.in_([Split.TRAIN, Split.VALID]))
            .order_by(
                RecallByDefinitionSplitKind.critic_definition_id,
                RecallByDefinitionSplitKind.critic_model,
                RecallByDefinitionSplitKind.example_kind,
                RecallByDefinitionSplitKind.split,
            )
            .limit(limit)
            .all()
        )

        console.print("\n[bold]Train vs Validation Performance (targeted mode - per-file + full-snapshot):[/bold]")
        console.print(build_table_from_schema(results, _build_performance_columns()))

        console.print()
        console.print("⚠️  = Warning: n_examples < 5 (small sample size, high variance)")
        console.print()
        console.print("Note: In targeted mode, you can see validation example filenames:")
        console.print("  SELECT files FROM examples WHERE snapshot_slug IN")
        console.print("    (SELECT slug FROM snapshots WHERE split = 'valid')")
        console.print()
        console.print("But ground truth (true_positives, false_positives) and execution")
        console.print("traces (events) remain hidden for validation split.")


def show_top_definitions(console: Console, limit: int = 10) -> None:
    """Show top-performing agent definitions on validation split.

    Definitions are ranked by occurrence-weighted recall (occurrences caught / catchable).

    Args:
        console: Rich console for output.
        limit: Maximum number of definitions to display.
    """

    with get_session() as session:
        # Query aggregated stats - use occurrences_caught_stats.mean for recall
        results = (
            session.query(RecallByDefinitionSplitKind)
            .filter(RecallByDefinitionSplitKind.split == Split.VALID)
            .limit(limit)
            .all()
        )
        # Sort in Python since occurrences_caught_stats is a composite type
        results = sorted(
            results,
            key=lambda r: r.occurrences_caught_stats.mean if r.occurrences_caught_stats else 0.0,
            reverse=True,
        )

        console.print(f"\n[bold]Top {limit} definitions on validation (by occurrence-weighted recall):[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Definition", lambda r: r.critic_definition_id, width=20),
            ColumnDef("Recall", lambda r: r.occurrences_caught_stats.mean if r.occurrences_caught_stats else None,
                      fmt_pct, justify="right"),
            ColumnDef("Caught", lambda r: (r.occurrences_caught_stats.mean * r.total_catchable_occurrences) if r.occurrences_caught_stats else 0.0, lambda v: f"{v:.1f}", justify="right"),
            ColumnDef("Catchable", lambda r: r.total_catchable_occurrences, str, justify="right"),
            ColumnDef("Runs", lambda r: r.status_counts.get("completed", 0), str, justify="right"),
        ]

        console.print(build_table_from_schema(results, columns))


def main():
    """Run all targeted mode metric examples."""
    console = Console()
    show_comprehensive_stats(console)
    print()
    show_train_vs_valid(console)
    print()
    show_top_definitions(console)


if __name__ == "__main__":
    main()
