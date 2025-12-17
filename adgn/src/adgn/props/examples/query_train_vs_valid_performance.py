"""Example: Query comprehensive prompt performance statistics with LCB-based ranking.

This script demonstrates how to get an overview of all prompts with their
performance on train and validation splits, similar to `adgn-properties stats`.
Prompts are sorted by Lower Confidence Bound (LCB) to prioritize consistent performers.

For each prompt, shows:
- Created timestamp and size
- Valid performance: mean recall, LCB, success/total counts, zero%, stuck%, context%
- Train performance: mean recall, LCB, success/total counts, zero%, stuck%, context%

Metrics:
- Mean recall: averaged over all runs (failures count as 0.0)
- LCB: lower confidence bound (mean - 1σ/√n), NULL if n < 2
- Success/total: successful runs vs all runs
- Zero%: percentage of successful runs with 0.0 recall (excludes failures)
- Stuck%: percentage of all runs that exceeded max_turns
- Context%: percentage of all runs that exceeded context_length

This helps identify:
- Which prompts have been evaluated on validation (many haven't)
- Which prompts show consistent, reliable performance (high LCB)
- Which prompts have high variance (low LCB despite good mean)
- Which prompts frequently get stuck (max_turns) or fail completely (zero-recall)
"""

from typing import Any

from rich.console import Console

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.cli.cmd_stats import STATS_TABLE_LEGEND
from adgn.props.db import get_session
from adgn.props.db.query_builders import query_prompt_performance_stats
from adgn.props.display import short_sha
from adgn.props.display import ColumnDef, build_table_from_schema


def format_stats(stats) -> str:
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


def main():
    """Display comprehensive prompt statistics across splits."""
    setup_agent_database()
    console = Console()

    with get_session() as session:
        results = query_prompt_performance_stats(session, limit=50)

        if not results:
            console.print("No prompts found in database.")
            return

        console.print(f"\n[bold]Prompt Performance Overview ({len(results)} most recent prompts, sorted by LCB)[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("SHA", lambda r: r.prompt_sha256, short_sha, width=8),
            ColumnDef("Created", lambda r: r.created_at.strftime("%m-%d %H:%M"), width=12),
            ColumnDef("Len", lambda r: f"{r.prompt_length // 1000}k", width=5),
            ColumnDef("Valid", lambda r: format_stats(r.valid), width=40),
            ColumnDef("Train", lambda r: format_stats(r.train), width=40),
        ]

        console.print(build_table_from_schema(results, columns))

        console.print()
        console.print("Format: recall% lcb:X% (N) Zz Ss Cc")
        console.print(STATS_TABLE_LEGEND)


if __name__ == "__main__":
    main()
