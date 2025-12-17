"""Example: Query train vs validation performance in targeted mode.

In targeted mode, validation includes both per-file and full-snapshot examples.
The examples table IS accessible (filenames only - no ground truth or traces).
All performance metrics are queried via the aggregated_recall_by_prompt view.

Key difference from whole-repo mode:
- Both splits: Use aggregated_recall_by_prompt view (includes n_examples, n_runs, ucb, lcb)
- Validation: Can see example filenames (but not ground truth or traces)

IMPORTANT: Check n_examples >= 5 before trusting validation metrics. Small sample
sizes have high variance. The ucb/lcb bounds quantify uncertainty.
"""

from typing import Any

from rich.console import Console
from sqlalchemy.orm import Session

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import AggregatedRecallByPrompt
from adgn.props.display import short_sha
from adgn.props.display import ColumnDef, build_table_from_schema
from adgn.props.splits import Split


def build_performance_columns() -> list[ColumnDef[Any, Any]]:
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


def main():
    """Display train vs validation performance comparison for targeted mode."""
    setup_agent_database()
    console = Console()

    with get_session() as session:
        # Single query for both train and valid splits
        results = (
            session.query(AggregatedRecallByPrompt)
            .filter(AggregatedRecallByPrompt.split.in_([Split.TRAIN, Split.VALID]))
            .order_by(
                AggregatedRecallByPrompt.prompt_sha256,
                AggregatedRecallByPrompt.critic_model,
                AggregatedRecallByPrompt.scope_kind,
                AggregatedRecallByPrompt.split,
            )
            .limit(40)
            .all()
        )

        console.print("\n[bold]Train vs Validation Performance (targeted mode - per-file + full-snapshot):[/bold]")
        console.print(build_table_from_schema(results, build_performance_columns()))

        console.print()
        console.print("⚠️  = Warning: n_examples < 5 (small sample size, high variance)")
        console.print()
        console.print("Note: In targeted mode, you can see validation example filenames:")
        console.print("  SELECT files FROM examples WHERE snapshot_slug IN")
        console.print("    (SELECT slug FROM snapshots WHERE split = 'valid')")
        console.print()
        console.print("But ground truth (true_positives, false_positives) and execution")
        console.print("traces (events) remain hidden for validation split.")


if __name__ == "__main__":
    main()
