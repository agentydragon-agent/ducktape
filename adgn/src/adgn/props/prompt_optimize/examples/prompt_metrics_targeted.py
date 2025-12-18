"""Prompt performance metrics for targeted mode.

In targeted mode, validation includes both per-file and full-snapshot examples.
The examples table IS accessible (filenames only - no ground truth or traces).
All performance metrics are queried via views directly.

IMPORTANT: This module is ONLY compatible with targeted mode. In whole-repo mode,
the occurrence_credits view is RLS-blocked for VALID split. Use
prompt_metrics_whole_repo.py instead.

Functions:
- show_comprehensive_stats(): Display prompt overview with LCB-based ranking
- show_train_vs_valid(): Compare train vs validation performance
- show_top_prompts(): Show top-performing prompts on validation

Key views used:
- occurrence_credits: Per-occurrence recall credits (TRAIN split only in whole-repo mode)
- aggregated_recall_by_prompt: Pre-aggregated stats with n_examples, ucb, lcb
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from sqlalchemy import select

from adgn.props.cli.cmd_stats import STATS_TABLE_LEGEND
from adgn.props.db import get_session
from adgn.props.db.models import AggregatedRecallByPrompt, Prompt
from adgn.props.db.query_builders import SplitPerformanceStats, query_prompt_performance_stats
from adgn.props.display import ColumnDef, build_table_from_schema, short_sha
from adgn.props.splits import Split


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
        ColumnDef("Prompt", lambda r: r.prompt_sha256, short_sha, width=8),
        ColumnDef("Model", lambda r: r.critic_model[:12], width=15),
        ColumnDef("Scope", lambda r: r.scope_kind, width=18),
        ColumnDef("N", lambda r: r.n_examples, str, justify="right", width=5),
        ColumnDef("Runs", lambda r: r.n_runs, str, justify="right", width=5),
        ColumnDef("Recall", lambda r: r.recall, lambda v: f"{v:.1%}" if v is not None else "-", justify="right", width=7),
        ColumnDef("UCB", lambda r: r.ucb, lambda v: f"{v:.1%}" if v is not None else "-", justify="right", width=7),
        ColumnDef("LCB", lambda r: r.lcb, lambda v: f"{v:.1%}" if v is not None else "-", justify="right", width=7),
        ColumnDef("", lambda r: " ⚠️" if r.split == Split.VALID and r.n_examples < 5 else "", width=3),
    ]


class _ExpandedStatsRow(BaseModel):
    """Row for expanded stats display (one row per prompt/split/scope_kind)."""

    prompt_sha256: str
    created_at: datetime
    split: Split
    scope_kind: str
    stats: SplitPerformanceStats


def show_comprehensive_stats(limit: int = 50) -> None:
    """Display comprehensive prompt statistics across splits and scope kinds.

    Shows for each (prompt, split, scope_kind) combination:
    - Created timestamp
    - Split and scope kind
    - Performance metrics: mean recall, LCB, success/total counts, zero%, stuck%, context%

    Prompts are sorted by creation date (most recent first).
    """
    console = Console()

    with get_session() as session:
        results = query_prompt_performance_stats(session, limit=limit)

        if not results:
            console.print("No prompts found in database.")
            return

        # Expand rows: one per (prompt, split, scope_kind)
        expanded_rows: list[_ExpandedStatsRow] = []
        for row in results:
            for (split, scope_kind), stats in row.stats.items():
                expanded_rows.append(
                    _ExpandedStatsRow(
                        prompt_sha256=row.prompt_sha256,
                        created_at=row.created_at,
                        split=split,
                        scope_kind=scope_kind,
                        stats=stats,
                    )
                )

        console.print(
            f"\n[bold]Prompt Performance Overview ({len(results)} prompts, "
            f"{len(expanded_rows)} rows by split/scope)[/bold]"
        )

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("SHA", lambda r: r.prompt_sha256, short_sha, width=8),
            ColumnDef("Created", lambda r: r.created_at.strftime("%m-%d %H:%M"), width=12),
            ColumnDef("Split", lambda r: r.split.value, width=6),
            ColumnDef("Scope", lambda r: r.scope_kind[:15], width=16),
            ColumnDef("Stats", lambda r: _format_split_stats(r.stats), width=45),
        ]

        console.print(build_table_from_schema(expanded_rows, columns))

        console.print()
        console.print("Format: recall% lcb:X% (N) Zz Ss Cc")
        console.print(STATS_TABLE_LEGEND)


def show_train_vs_valid(limit: int = 40) -> None:
    """Display train vs validation performance comparison for targeted mode.

    In targeted mode, both per-file and full-snapshot examples are visible for
    validation. Query uses aggregated_recall_by_prompt view directly.

    IMPORTANT: Check n_examples >= 5 before trusting validation metrics.
    Small sample sizes have high variance.
    """
    console = Console()

    with get_session() as session:
        results = (
            session.query(AggregatedRecallByPrompt)
            .filter(AggregatedRecallByPrompt.split.in_([Split.TRAIN, Split.VALID]))
            .order_by(
                AggregatedRecallByPrompt.prompt_sha256,
                AggregatedRecallByPrompt.critic_model,
                AggregatedRecallByPrompt.scope_kind,
                AggregatedRecallByPrompt.split,
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


def show_top_prompts(limit: int = 10) -> None:
    """Show top-performing prompts on validation split.

    Prompts are ranked by occurrence-weighted recall (occurrences caught / catchable).
    """
    console = Console()

    with get_session() as session:
        query = (
            select(
                AggregatedRecallByPrompt.prompt_sha256,
                AggregatedRecallByPrompt.recall,
                AggregatedRecallByPrompt.avg_occurrences_caught_overall,
                AggregatedRecallByPrompt.avg_catchable_occurrences,
                AggregatedRecallByPrompt.total_catchable_occurrences,
                AggregatedRecallByPrompt.n_successful,
            )
            .where(AggregatedRecallByPrompt.split == Split.VALID)
            .order_by(AggregatedRecallByPrompt.recall.desc().nulls_last())
            .limit(limit)
        )

        top_prompts = session.execute(query).fetchall()

        # Enrich with prompt text previews
        rows_with_preview = []
        for row in top_prompts:
            prompt = session.query(Prompt).filter_by(prompt_sha256=row.prompt_sha256).first()
            preview = prompt.prompt_text[:100].replace("\n", " ") if prompt else "(not found)"
            rows_with_preview.append((row, preview))

        console.print(f"\n[bold]Top {limit} prompts on validation (by occurrence-weighted recall):[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Prompt", lambda r: r[0].prompt_sha256, short_sha, width=8),
            ColumnDef("Recall", lambda r: r[0].recall,
                      lambda v: f"{v:.1%}" if v is not None else "-", justify="right"),
            ColumnDef("Caught", lambda r: r[0].avg_occurrences_caught_overall, lambda v: f"{v:.1f}", justify="right"),
            ColumnDef("Catchable", lambda r: r[0].total_catchable_occurrences, str, justify="right"),
            ColumnDef("Runs", lambda r: r[0].n_successful, str, justify="right"),
            ColumnDef("Preview", lambda r: r[1], width=40),
        ]

        console.print(build_table_from_schema(rows_with_preview, columns))


def main():
    """Run all targeted mode metric examples."""
    show_comprehensive_stats()
    print()
    show_train_vs_valid()
    print()
    show_top_prompts()


if __name__ == "__main__":
    main()
