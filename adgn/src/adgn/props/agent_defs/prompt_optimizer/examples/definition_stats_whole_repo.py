"""Definition performance statistics for whole-repo mode.

In whole-repo mode, validation uses full-snapshot examples only and the examples
table is NOT accessible (RLS blocks). Validation performance is queried via the
get_validation_full_snapshot_aggregates() PostgreSQL SECURITY DEFINER function.

NOTE: `get_validation_full_snapshot_aggregates()` is a **PostgreSQL function** (not Python).
Call it via SQL: `SELECT * FROM get_validation_full_snapshot_aggregates()`.
There is NO Python export for this function - it only exists in the database.

This module is specifically for whole-repo mode. For targeted mode (where per-file
examples are visible), use definition_stats_targeted.py instead.

Key differences from targeted mode:
- Validation: Use SQL `SELECT * FROM get_validation_full_snapshot_aggregates()` (per-run results)
- Training: Use aggregated_recall_by_definition view (pre-aggregated stats)
"""

from typing import Any

from rich.console import Console
from sqlalchemy import text

from adgn.props.db import get_session
from adgn.props.display import ColumnDef, build_table_from_schema


def _build_performance_columns() -> list[ColumnDef[Any, Any]]:
    """Build column definitions for combined train/valid performance table."""
    return [
        ColumnDef("Split", lambda r: r.split, width=6),
        ColumnDef("Definition", lambda r: r.agent_definition_id, width=20),
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
    - SECURITY DEFINER function get_validation_full_snapshot_aggregates() for validation
    - aggregated_recall_by_definition view for training

    In whole-repo mode, n_runs ≈ n_examples (each run is a full-snapshot example).
    Metrics are aggregated over all grader models.
    """
    console = Console()

    with get_session() as session:
        # Single query combining train (from view) and valid (from function with computed UCB/LCB)
        results = session.execute(
            text("""
            -- Validation: compute stats from SECURITY DEFINER function
            -- Note: get_validation_full_snapshot_aggregates() returns per-run data
            -- For whole-repo mode, n_runs ≈ n_examples (each run is a full-snapshot example)
            WITH valid_stats AS (
                SELECT
                    'valid'::text AS split,
                    critic_definition_id AS agent_definition_id,
                    critic_model,
                    COUNT(*) FILTER (WHERE status = 'completed') AS n_successful,
                    COUNT(*) FILTER (WHERE status = 'max_turns_exceeded') AS n_max_turns,
                    COUNT(*) FILTER (WHERE status = 'context_length_exceeded') AS n_context,
                    AVG(total_credit / NULLIF(n_occurrences, 0)) AS recall,
                    AVG(total_credit / NULLIF(n_occurrences, 0)) + STDDEV_SAMP(total_credit / NULLIF(n_occurrences, 0)) / SQRT(NULLIF(COUNT(*), 0)) AS ucb,
                    AVG(total_credit / NULLIF(n_occurrences, 0)) - STDDEV_SAMP(total_credit / NULLIF(n_occurrences, 0)) / SQRT(NULLIF(COUNT(*), 0)) AS lcb
                FROM get_validation_full_snapshot_aggregates()
                GROUP BY critic_definition_id, critic_model
            ),
            -- Training: query pre-aggregated view
            -- Note: aggregated_recall_by_definition aggregates over all graders (no grader_model column)
            -- status_counts is JSONB, occurrences_caught_stats is stats_with_ci composite type
            train_stats AS (
                SELECT
                    split::text,
                    critic_definition_id AS agent_definition_id,
                    critic_model,
                    (status_counts->>'completed')::int AS n_successful,
                    (status_counts->>'max_turns_exceeded')::int AS n_max_turns,
                    (status_counts->>'context_length_exceeded')::int AS n_context,
                    (occurrences_caught_stats).mean AS recall,
                    (occurrences_caught_stats).ucb95 AS ucb,
                    (occurrences_caught_stats).lcb95 AS lcb
                FROM aggregated_recall_by_definition
                WHERE split = 'train' AND example_kind = 'whole_snapshot'
            )
            -- Combine and order
            SELECT * FROM valid_stats
            UNION ALL
            SELECT * FROM train_stats
            ORDER BY agent_definition_id, critic_model, split
            LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

        console.print("\n[bold]Train vs Validation Performance (whole-repo mode - full-snapshot only):[/bold]")
        console.print(build_table_from_schema(results, _build_performance_columns()))

        console.print()
        console.print("Note: In whole-repo mode, validation examples table is NOT accessible.")
        console.print("Use get_validation_full_snapshot_aggregates() to query validation performance.")


def main():
    """Run whole-repo mode metric examples."""
    show_train_vs_valid()


if __name__ == "__main__":
    main()
