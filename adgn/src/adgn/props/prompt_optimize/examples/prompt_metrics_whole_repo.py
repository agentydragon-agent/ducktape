"""Prompt performance metrics for whole-repo mode.

In whole-repo mode, validation uses full-snapshot examples only and the examples
table is NOT accessible (RLS blocks). Validation performance is queried via the
get_validation_run_aggregates() PostgreSQL SECURITY DEFINER function.

NOTE: `get_validation_run_aggregates()` is a **PostgreSQL function** (not Python).
Call it via SQL: `SELECT * FROM get_validation_run_aggregates()`.
There is NO Python export for this function - it only exists in the database.

This module is specifically for whole-repo mode. For targeted mode (where per-file
examples are visible), use prompt_metrics_targeted.py instead.

Key differences from targeted mode:
- Validation: Use SQL `SELECT * FROM get_validation_run_aggregates()` (per-run results)
- Training: Use aggregated_recall_by_prompt view (pre-aggregated stats)
"""

from typing import Any

from rich.console import Console
from sqlalchemy import text

from adgn.props.db import get_session
from adgn.props.display import ColumnDef, build_table_from_schema, short_sha


def _build_performance_columns() -> list[ColumnDef[Any, Any]]:
    """Build column definitions for combined train/valid performance table."""
    return [
        ColumnDef("Split", lambda r: r.split, width=6),
        ColumnDef("Prompt", lambda r: r.prompt_sha256, short_sha, width=8),
        ColumnDef("Critic", lambda r: r.critic_model[:12], width=12),
        ColumnDef("OK", lambda r: r.n_successful, str, justify="right", width=4),
        ColumnDef("MaxT", lambda r: r.n_max_turns, str, justify="right", width=5),
        ColumnDef("CtxL", lambda r: r.n_context, str, justify="right", width=5),
        ColumnDef("Recall", lambda r: r.recall, lambda v: f"{v:.1%}", justify="right", width=7),
        ColumnDef("UCB", lambda r: r.ucb, lambda v: f"{v:.1%}", justify="right", width=7),
        ColumnDef("LCB", lambda r: r.lcb, lambda v: f"{v:.1%}", justify="right", width=7),
    ]


def show_train_vs_valid(limit: int = 20) -> None:
    """Display train vs validation performance comparison for whole-repo mode.

    Uses:
    - SECURITY DEFINER function get_validation_run_aggregates() for validation
    - aggregated_recall_by_prompt view for training

    In whole-repo mode, n_runs ≈ n_examples (each run is a full-snapshot example).
    Metrics are aggregated over all grader models.
    """
    console = Console()

    with get_session() as session:
        # Single query combining train (from view) and valid (from function with computed UCB/LCB)
        results = session.execute(
            text("""
            -- Validation: compute stats from SECURITY DEFINER function
            -- Note: get_validation_run_aggregates() returns per-run data
            -- For whole-repo mode, n_runs ≈ n_examples (each run is a full-snapshot example)
            -- Note: Aggregates over all graders (grader_model removed in migration 20251217000001)
            WITH valid_stats AS (
                SELECT
                    'valid'::text AS split,
                    prompt_sha256,
                    critic_model,
                    COUNT(*) FILTER (WHERE status = 'completed') AS n_successful,
                    COUNT(*) FILTER (WHERE status = 'max_turns_exceeded') AS n_max_turns,
                    COUNT(*) FILTER (WHERE status = 'context_length_exceeded') AS n_context,
                    AVG(total_credit / n_occurrences) AS recall,
                    AVG(total_credit / n_occurrences) + STDDEV_SAMP(total_credit / n_occurrences) / SQRT(COUNT(*)) AS ucb,
                    AVG(total_credit / n_occurrences) - STDDEV_SAMP(total_credit / n_occurrences) / SQRT(COUNT(*)) AS lcb
                FROM get_validation_run_aggregates()
                GROUP BY prompt_sha256, critic_model
            ),
            -- Training: query pre-aggregated view
            -- Note: aggregated_recall_by_prompt aggregates over all graders (no grader_model column)
            train_stats AS (
                SELECT
                    split::text,
                    prompt_sha256,
                    critic_model,
                    n_successful,
                    n_max_turns_exceeded AS n_max_turns,
                    n_context_length_exceeded AS n_context,
                    avg_occurrences_caught_overall / NULLIF(avg_catchable_occurrences, 0) AS recall,
                    (avg_occurrences_caught_among_successful + SQRT(COALESCE(occurrences_variance_among_successful, 0)) / SQRT(GREATEST(n_successful, 1)))
                        / NULLIF(avg_catchable_occurrences, 0) AS ucb,
                    (avg_occurrences_caught_among_successful - SQRT(COALESCE(occurrences_variance_among_successful, 0)) / SQRT(GREATEST(n_successful, 1)))
                        / NULLIF(avg_catchable_occurrences, 0) AS lcb
                FROM aggregated_recall_by_prompt
                WHERE split = 'train' AND scope_kind = 'entire_snapshot'
            )
            -- Combine and order
            SELECT * FROM valid_stats
            UNION ALL
            SELECT * FROM train_stats
            ORDER BY prompt_sha256, critic_model, split
            LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

        console.print("\n[bold]Train vs Validation Performance (whole-repo mode - full-snapshot only):[/bold]")
        console.print(build_table_from_schema(results, _build_performance_columns()))

        console.print()
        console.print("Note: In whole-repo mode, validation examples table is NOT accessible.")
        console.print("Use get_validation_run_aggregates() to query validation performance.")
        console.print("Metrics are aggregated over all grader models (migration 20251217000001).")


def main():
    """Run whole-repo mode metric examples."""
    show_train_vs_valid()


if __name__ == "__main__":
    main()
